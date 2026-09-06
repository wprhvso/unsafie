const std = @import("std");
const posix = std.posix;
const HmacSha256 = std.crypto.auth.hmac.sha2.HmacSha256;

const SID_LEN = 16;
const HEAD_MAX = 16 * 1024;
const BUF = 32 * 1024;

const Config = struct {
    port: u16,
    path: []const u8,
    psk: []const u8,
    skew: i64,
};

const Session = struct {
    target: posix.socket_t = -1,
    connected: bool = false,
    dead: bool = false,
    mutex: std.Thread.Mutex = .{},
    cond: std.Thread.Condition = .{},
};

const Manager = struct {
    alloc: std.mem.Allocator,
    mutex: std.Thread.Mutex = .{},
    map: std.AutoHashMap([SID_LEN]u8, *Session),

    fn get_or_create(self: *Manager, sid: [SID_LEN]u8) !*Session {
        self.mutex.lock();
        defer self.mutex.unlock();
        if (self.map.get(sid)) |s| return s;
        const s = try self.alloc.create(Session);
        s.* = .{};
        try self.map.put(sid, s);
        return s;
    }

    fn drop(self: *Manager, sid: [SID_LEN]u8) void {
        self.mutex.lock();
        defer self.mutex.unlock();
        if (self.map.fetchRemove(sid)) |kv| self.alloc.destroy(kv.value);
    }
};

var manager: Manager = undefined;
var config: Config = undefined;

pub fn main() !void {
    const alloc = std.heap.page_allocator;
    config = .{
        .port = envU16("RELAY_PORT", 8080),
        .path = env(alloc, "RELAY_PATH", "/api/v1/events"),
        .psk = env(alloc, "RELAY_PSK", ""),
        .skew = 30,
    };
    manager = .{ .alloc = alloc, .map = std.AutoHashMap([SID_LEN]u8, *Session).init(alloc) };

    const addr = try std.net.Address.parseIp("127.0.0.1", config.port);
    var server = try addr.listen(.{ .reuse_address = true });
    std.log.info("relay listening on {d}", .{config.port});

    while (true) {
        const conn = server.accept() catch continue;
        const t = std.Thread.spawn(.{}, handle, .{conn.stream.handle}) catch {
            posix.close(conn.stream.handle);
            continue;
        };
        t.detach();
    }
}

fn handle(fd: posix.socket_t) void {
    handleConn(fd) catch {};
    posix.close(fd);
}

fn handleConn(fd: posix.socket_t) !void {
    var head: [HEAD_MAX]u8 = undefined;
    const head_len = try readHead(fd, &head);
    const req = head[0..head_len];

    const line_end = std.mem.indexOf(u8, req, "\r\n") orelse return fallback(fd);
    const line = req[0..line_end];
    var it = std.mem.tokenizeScalar(u8, line, ' ');
    const method = it.next() orelse return fallback(fd);
    const path = it.next() orelse return fallback(fd);

    const q = std.mem.indexOfScalar(u8, path, '?');
    const bare = if (q) |i| path[0..i] else path;
    if (!std.mem.eql(u8, bare, config.path)) return fallback(fd);

    const body_start = (std.mem.indexOf(u8, req, "\r\n\r\n") orelse return fallback(fd)) + 4;
    const leftover = req[body_start..head_len];

    if (std.mem.eql(u8, method, "POST")) return up(fd, req, leftover);
    if (std.mem.eql(u8, method, "GET")) return down(fd, req);
    return fallback(fd);
}

fn up(fd: posix.socket_t, req: []const u8, leftover: []const u8) !void {
    const chunked = header(req, "transfer-encoding") != null;
    var reader = BodyReader.init(fd, leftover, chunked);

    var pre: [4]u8 = undefined;
    try reader.exact(&pre);
    const ver = pre[0];
    const flags = pre[1];
    const atyp = pre[2];
    const alen = pre[3];
    if (ver != 1) return fallback(fd);

    var addrbuf: [256]u8 = undefined;
    const addr_size: usize = switch (atyp) {
        1 => 4,
        4 => 16,
        3 => alen,
        else => return fallback(fd),
    };
    try reader.exact(addrbuf[0..addr_size]);
    var tail: [2 + SID_LEN + 8 + 32]u8 = undefined;
    try reader.exact(&tail);

    const port = std.mem.readInt(u16, tail[0..2], .big);
    var sid: [SID_LEN]u8 = undefined;
    @memcpy(&sid, tail[2 .. 2 + SID_LEN]);
    const ts = std.mem.readInt(i64, tail[2 + SID_LEN .. 2 + SID_LEN + 8], .big);
    const mac = tail[2 + SID_LEN + 8 ..];

    const preamble_len = 4 + addr_size + 2 + SID_LEN + 8;
    var scratch: [512]u8 = undefined;
    @memcpy(scratch[0..4], &pre);
    @memcpy(scratch[4 .. 4 + addr_size], addrbuf[0..addr_size]);
    @memcpy(scratch[4 + addr_size ..][0 .. 2 + SID_LEN + 8], tail[0 .. 2 + SID_LEN + 8]);
    if (!verify(scratch[0..preamble_len], mac, ts)) return fallback(fd);

    const session = try manager.get_or_create(sid);
    const target = dial(atyp, addrbuf[0..addr_size], port, flags) catch {
        session.mutex.lock();
        session.dead = true;
        session.cond.broadcast();
        session.mutex.unlock();
        return respondEmpty(fd);
    };
    session.mutex.lock();
    session.target = target;
    session.connected = true;
    session.cond.broadcast();
    session.mutex.unlock();

    pump(&reader, target) catch {};
    posix.shutdown(target, .send) catch {};
    respondEmpty(fd) catch {};
}

fn down(fd: posix.socket_t, req: []const u8) !void {
    const cookie = header(req, "cookie") orelse return fallback(fd);
    const sid = parseCookie(cookie) orelse return fallback(fd);

    const session = try manager.get_or_create(sid);
    session.mutex.lock();
    var waited: usize = 0;
    while (!session.connected and !session.dead and waited < 100) : (waited += 1) {
        session.cond.timedWait(&session.mutex, 100 * std.time.ns_per_ms) catch {};
    }
    const target = session.target;
    const dead = session.dead or !session.connected;
    session.mutex.unlock();
    if (dead) return fallback(fd);

    _ = try posix.write(fd, "HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nCache-Control: no-cache\r\n\r\n");
    var buf: [BUF]u8 = undefined;
    while (true) {
        const n = posix.read(target, &buf) catch break;
        if (n == 0) break;
        _ = posix.write(fd, buf[0..n]) catch break;
    }
    manager.drop(sid);
}

fn pump(reader: *BodyReader, target: posix.socket_t) !void {
    var buf: [BUF]u8 = undefined;
    while (true) {
        const n = try reader.read(&buf);
        if (n == 0) break;
        _ = try posix.write(target, buf[0..n]);
    }
}

fn dial(atyp: u8, addr: []const u8, port: u16, flags: u8) !posix.socket_t {
    const stype: u32 = if (flags & 1 == 1) posix.SOCK.DGRAM else posix.SOCK.STREAM;
    var address: std.net.Address = undefined;
    switch (atyp) {
        1 => address = std.net.Address.initIp4(addr[0..4].*, port),
        4 => address = std.net.Address.initIp6(addr[0..16].*, port, 0, 0),
        3 => {
            const list = try std.net.getAddressList(std.heap.page_allocator, addr, port);
            defer list.deinit();
            if (list.addrs.len == 0) return error.NoAddress;
            address = list.addrs[0];
        },
        else => return error.BadAddr,
    }
    const sock = try posix.socket(address.any.family, stype, 0);
    errdefer posix.close(sock);
    try posix.connect(sock, &address.any, address.getOsSockLen());
    return sock;
}

fn verify(preamble: []const u8, mac: []const u8, ts: i64) bool {
    const now = std.time.timestamp();
    if (@abs(now - ts) > config.skew) return false;
    var out: [32]u8 = undefined;
    HmacSha256.create(&out, preamble, config.psk);
    return std.crypto.utils.timingSafeEql([32]u8, out, mac[0..32].*);
}

fn parseCookie(cookie: []const u8) ?[SID_LEN]u8 {
    const eq = std.mem.indexOfScalar(u8, cookie, '=') orelse return null;
    const val = std.mem.trim(u8, cookie[eq + 1 ..], " ;");
    const dot = std.mem.indexOfScalar(u8, val, '.') orelse return null;
    const b64 = val[0..dot];
    var sid: [SID_LEN]u8 = undefined;
    const dec = std.base64.url_safe_no_pad.Decoder;
    dec.decode(&sid, b64) catch return null;
    return sid;
}

const BodyReader = struct {
    fd: posix.socket_t,
    buf: []const u8,
    off: usize,
    chunked: bool,
    remaining: usize = 0,
    done: bool = false,
    store: [BUF]u8 = undefined,

    fn init(fd: posix.socket_t, leftover: []const u8, chunked: bool) BodyReader {
        var r = BodyReader{ .fd = fd, .buf = &.{}, .off = 0, .chunked = chunked };
        @memcpy(r.store[0..leftover.len], leftover);
        r.buf = r.store[0..leftover.len];
        return r;
    }

    fn fill(self: *BodyReader) !void {
        if (self.off < self.buf.len) return;
        const n = try posix.read(self.fd, &self.store);
        self.buf = self.store[0..n];
        self.off = 0;
        if (n == 0) self.done = true;
    }

    fn byte(self: *BodyReader) !u8 {
        try self.fill();
        if (self.done) return error.Eof;
        const b = self.buf[self.off];
        self.off += 1;
        return b;
    }

    fn read(self: *BodyReader, out: []u8) !usize {
        if (!self.chunked) {
            try self.fill();
            if (self.done) return 0;
            const n = @min(out.len, self.buf.len - self.off);
            @memcpy(out[0..n], self.buf[self.off .. self.off + n]);
            self.off += n;
            return n;
        }
        if (self.remaining == 0) {
            var line: [16]u8 = undefined;
            var i: usize = 0;
            while (i < line.len) {
                const b = self.byte() catch return 0;
                if (b == '\r') {
                    _ = self.byte() catch {};
                    break;
                }
                line[i] = b;
                i += 1;
            }
            self.remaining = std.fmt.parseInt(usize, line[0..i], 16) catch 0;
            if (self.remaining == 0) return 0;
        }
        try self.fill();
        if (self.done) return 0;
        const n = @min(@min(out.len, self.remaining), self.buf.len - self.off);
        @memcpy(out[0..n], self.buf[self.off .. self.off + n]);
        self.off += n;
        self.remaining -= n;
        if (self.remaining == 0) {
            _ = self.byte() catch {};
            _ = self.byte() catch {};
        }
        return n;
    }

    fn exact(self: *BodyReader, out: []u8) !void {
        var got: usize = 0;
        while (got < out.len) {
            const n = try self.read(out[got..]);
            if (n == 0) return error.Eof;
            got += n;
        }
    }
};

fn readHead(fd: posix.socket_t, buf: []u8) !usize {
    var len: usize = 0;
    while (len < buf.len) {
        const n = try posix.read(fd, buf[len..]);
        if (n == 0) break;
        len += n;
        if (std.mem.indexOf(u8, buf[0..len], "\r\n\r\n") != null) break;
    }
    return len;
}

fn header(req: []const u8, name: []const u8) ?[]const u8 {
    var it = std.mem.splitSequence(u8, req, "\r\n");
    _ = it.next();
    while (it.next()) |line| {
        const colon = std.mem.indexOfScalar(u8, line, ':') orelse continue;
        if (std.ascii.eqlIgnoreCase(std.mem.trim(u8, line[0..colon], " "), name))
            return std.mem.trim(u8, line[colon + 1 ..], " ");
    }
    return null;
}

fn fallback(fd: posix.socket_t) !void {
    _ = try posix.write(fd, "HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n");
}

fn respondEmpty(fd: posix.socket_t) !void {
    _ = try posix.write(fd, "HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n");
}

fn env(alloc: std.mem.Allocator, key: []const u8, default: []const u8) []const u8 {
    return std.process.getEnvVarOwned(alloc, key) catch default;
}

fn envU16(key: []const u8, default: u16) u16 {
    var buf: [16]u8 = undefined;
    const v = std.process.getEnvVarOwned(std.heap.page_allocator, key) catch return default;
    _ = buf;
    return std.fmt.parseInt(u16, v, 10) catch default;
}
