const std = @import("std");
const posix = std.posix;
const linux = std.os.linux;

const http = @import("http.zig");
const usp = @import("usp.zig");
const ids = @import("session.zig");
const buffers = @import("ring.zig");
const dns = @import("dns.zig");
const log = @import("log.zig");

const Ring = buffers.Ring;
const Buffer = buffers.Buffer;

pub const Config = struct {
    listen: std.net.Address,
    resolver: std.net.Address,
    region: []const u8 = "",
    country: []const u8 = "",
    asn: u32 = 0,
    stream_window: u32 = 512 * 1024,
    session_window: u32 = 12 * 1024 * 1024,
    replay_bytes: usize = 4 * 1024 * 1024,
    max_streams: u32 = 4096,
    max_sessions: u32 = 8192,
    idle_ms: i64 = 120_000,
    connect_ms: i64 = 10_000,
    dns_ms: i64 = 5_000,
    keepalive_ms: u32 = 15_000,
    slot: u8 = 0,
};

pub const Stats = struct {
    sessions_opened: u64 = 0,
    sessions_resumed: u64 = 0,
    legs_up: u64 = 0,
    legs_down: u64 = 0,
    streams_opened: u64 = 0,
    streams_refused: u64 = 0,
    dns_queries: u64 = 0,
    dns_failures: u64 = 0,
    bytes_in: u64 = 0,
    bytes_out: u64 = 0,
    replayed: u64 = 0,
    resume_failures: u64 = 0,
    protocol_errors: u64 = 0,
};

const Kind = enum { listener, conn, egress, dns };

const Reg = struct {
    kind: Kind,
    fd: posix.fd_t = -1,
    events: u32 = 0,
};

const Role = enum { none, up, down };

const read_chunk: usize = 32 * 1024;
const out_high_water: usize = 1024 * 1024;
const egress_high_water: usize = 512 * 1024;

pub const Conn = struct {
    reg: Reg = .{ .kind = .conn },
    edge: *Edge,
    in: Buffer,
    out: Buffer,
    head_done: bool = false,
    request: http.Request = .{},
    role: Role = .none,
    session: ?*Session = null,
    dec: http.ChunkDecoder = .{},
    body_left: ?u64 = null,
    close_after: bool = false,
    dying: bool = false,
    dead_next: ?*Conn = null,
    last: i64 = 0,
};

const StreamState = enum { resolving, connecting, open, closed };

pub const Stream = struct {
    reg: Reg = .{ .kind = .egress },
    id: u16,
    session: *Session,
    state: StreamState = .connecting,
    udp: bool = false,
    addr: std.net.Address = undefined,
    name_buf: [256]u8 = undefined,
    name_len: usize = 0,
    port: u16 = 0,
    query: u16 = 0,
    deadline: i64 = 0,
    send_credit: i64 = 0,
    to_egress: Buffer,
    want_write: bool = false,
    paused: bool = false,
    credited: u64 = 0,
    fin_client: bool = false,
    opened: bool = false,
    dead_next: ?*Stream = null,
};

pub const Session = struct {
    id: [ids.id_len]u8 = undefined,
    edge: *Edge,
    streams: std.AutoHashMap(u16, *Stream),
    up: ?*Conn = null,
    down: ?*Conn = null,

    up_consumed: u64 = 0,
    up_skip: u64 = 0,
    down_off: u64 = 0,

    replay: Ring,
    out: Buffer,
    wire: Buffer,

    head: [usp.header_size]u8 = undefined,
    head_len: usize = 0,
    payload: Buffer,
    want: usize = 0,
    in_body: bool = false,

    send_credit: i64 = 0,
    recv_credited: u64 = 0,
    stream_window: u32 = 0,
    greeted: bool = false,

    created: i64 = 0,
    last: i64 = 0,
    dead: bool = false,
    dead_next: ?*Session = null,
};

pub const Edge = struct {
    allocator: std.mem.Allocator,
    cfg: Config,
    epfd: posix.fd_t = -1,
    listener: Reg = .{ .kind = .listener },
    dns_reg: Reg = .{ .kind = .dns },
    dns_id: u16 = 1,
    sessions: std.StringHashMap(*Session),
    pending: std.AutoHashMap(u16, *Stream),
    stats: Stats = .{},
    scratch: []u8,
    running: bool = true,
    dead_conns: ?*Conn = null,
    dead_streams: ?*Stream = null,
    dead_sessions: ?*Session = null,

    pub fn init(allocator: std.mem.Allocator, cfg: Config) !*Edge {
        const self = try allocator.create(Edge);
        self.* = .{
            .allocator = allocator,
            .cfg = cfg,
            .sessions = std.StringHashMap(*Session).init(allocator),
            .pending = std.AutoHashMap(u16, *Stream).init(allocator),
            .scratch = try allocator.alloc(u8, 1 << 20),
        };

        self.epfd = try posix.epoll_create1(linux.EPOLL.CLOEXEC);
        self.listener.fd = try openListener(cfg.listen);
        try self.arm(&self.listener, linux.EPOLL.IN);

        self.dns_reg.fd = try posix.socket(
            cfg.resolver.any.family,
            posix.SOCK.DGRAM | posix.SOCK.NONBLOCK | posix.SOCK.CLOEXEC,
            posix.IPPROTO.UDP,
        );
        try posix.connect(self.dns_reg.fd, &cfg.resolver.any, cfg.resolver.getOsSockLen());
        try self.arm(&self.dns_reg, linux.EPOLL.IN);

        return self;
    }

    pub fn deinit(self: *Edge) void {
        self.reap();
        var it = self.sessions.iterator();
        while (it.next()) |entry| self.freeSession(entry.value_ptr.*);
        self.sessions.deinit();
        self.pending.deinit();
        self.allocator.free(self.scratch);
        posix.close(self.dns_reg.fd);
        posix.close(self.listener.fd);
        posix.close(self.epfd);
        self.allocator.destroy(self);
    }

    fn arm(self: *Edge, reg: *Reg, events: u32) !void {
        var ev = linux.epoll_event{ .events = events, .data = .{ .ptr = @intFromPtr(reg) } };
        try posix.epoll_ctl(self.epfd, linux.EPOLL.CTL_ADD, reg.fd, &ev);
        reg.events = events;
    }

    fn rearm(self: *Edge, reg: *Reg, events: u32) void {
        if (reg.fd < 0 or reg.events == events) return;
        var ev = linux.epoll_event{ .events = events, .data = .{ .ptr = @intFromPtr(reg) } };
        posix.epoll_ctl(self.epfd, linux.EPOLL.CTL_MOD, reg.fd, &ev) catch return;
        reg.events = events;
    }

    fn disarm(self: *Edge, reg: *Reg) void {
        if (reg.fd < 0 or reg.events == 0) return;
        posix.epoll_ctl(self.epfd, linux.EPOLL.CTL_DEL, reg.fd, null) catch {};
        reg.events = 0;
    }

    pub fn run(self: *Edge) !void {
        var events: [512]linux.epoll_event = undefined;
        var next_tick = std.time.milliTimestamp();

        while (self.running) {
            const n = posix.epoll_wait(self.epfd, &events, 200);
            for (events[0..n]) |ev| {
                const reg: *Reg = @ptrFromInt(ev.data.ptr);
                switch (reg.kind) {
                    .listener => self.acceptAll(),
                    .conn => {
                        const conn: *Conn = @alignCast(@fieldParentPtr("reg", reg));
                        self.onConn(conn, ev.events);
                    },
                    .egress => {
                        const stream: *Stream = @alignCast(@fieldParentPtr("reg", reg));
                        self.onEgress(stream, ev.events);
                    },
                    .dns => self.onDns(),
                }
            }

            const now = std.time.milliTimestamp();
            if (now >= next_tick) {
                next_tick = now + 250;
                self.tick(now);
            }
            self.reap();
        }
    }

    fn acceptAll(self: *Edge) void {
        while (true) {
            const fd = posix.accept(self.listener.fd, null, null, posix.SOCK.NONBLOCK | posix.SOCK.CLOEXEC) catch return;
            setNoDelay(fd);

            const conn = self.allocator.create(Conn) catch {
                posix.close(fd);
                return;
            };
            conn.* = .{
                .edge = self,
                .in = Buffer.init(self.allocator),
                .out = Buffer.init(self.allocator),
                .last = std.time.milliTimestamp(),
            };
            conn.reg.fd = fd;
            self.arm(&conn.reg, linux.EPOLL.IN | linux.EPOLL.RDHUP) catch {
                posix.close(fd);
                conn.in.deinit();
                conn.out.deinit();
                self.allocator.destroy(conn);
                return;
            };
        }
    }

    fn closeConn(self: *Edge, conn: *Conn) void {
        if (conn.dying) return;
        conn.dying = true;

        if (conn.session) |s| {
            switch (conn.role) {
                .up => if (s.up == conn) {
                    s.up = null;
                },
                .down => if (s.down == conn) {
                    s.down = null;
                    s.wire.deinit();
                    s.wire = Buffer.init(self.allocator);
                },
                .none => {},
            }
        }

        self.disarm(&conn.reg);
        if (conn.reg.fd >= 0) posix.close(conn.reg.fd);
        conn.reg.fd = -1;
        conn.dead_next = self.dead_conns;
        self.dead_conns = conn;
    }

    fn reap(self: *Edge) void {
        while (self.dead_streams) |st| {
            self.dead_streams = st.dead_next;
            st.to_egress.deinit();
            self.allocator.destroy(st);
        }
        while (self.dead_conns) |conn| {
            self.dead_conns = conn.dead_next;
            conn.in.deinit();
            conn.out.deinit();
            self.allocator.destroy(conn);
        }
        while (self.dead_sessions) |s| {
            self.dead_sessions = s.dead_next;
            self.freeSession(s);
        }
    }

    fn onConn(self: *Edge, conn: *Conn, events: u32) void {
        if (events & (linux.EPOLL.HUP | linux.EPOLL.ERR) != 0) {
            self.closeConn(conn);
            return;
        }
        if (events & linux.EPOLL.OUT != 0) {
            self.flushConn(conn);
            if (conn.dying) return;
            if (conn.role == .down) {
                if (conn.session) |s| self.flushDown(s);
            }
        }
        if (events & (linux.EPOLL.IN | linux.EPOLL.RDHUP) != 0) {
            self.readConn(conn);
        }
    }

    fn readConn(self: *Edge, conn: *Conn) void {
        conn.last = std.time.milliTimestamp();

        while (true) {
            if (conn.role == .up) {
                if (conn.session) |s| {
                    if (s.out.size() > out_high_water) break;
                }
            }
            const dst = conn.in.tail(read_chunk) catch {
                self.closeConn(conn);
                return;
            };
            const n = posix.read(conn.reg.fd, dst) catch |err| {
                conn.in.len -= read_chunk;
                if (err == error.WouldBlock) break;
                self.closeConn(conn);
                return;
            };
            conn.in.len -= read_chunk - n;
            if (n == 0) {
                self.advance(conn);
                self.closeConn(conn);
                return;
            }
            self.stats.bytes_in += n;
            self.advance(conn);
            if (conn.dying) return;
            if (n < read_chunk) break;
        }
    }

    fn advance(self: *Edge, conn: *Conn) void {
        while (!conn.dying) {
            if (!conn.head_done) {
                const parsed = http.parse(conn.in.readable()) catch {
                    self.replyAndClose(conn, 400, "Bad Request", "bad request");
                    return;
                } orelse return;

                conn.request = parsed.request;
                conn.head_done = true;
                conn.in.consume(parsed.head_len);
                conn.dec = .{};
                conn.body_left = if (conn.request.chunked) null else conn.request.content_length orelse 0;

                if (conn.request.expect_continue) {
                    _ = conn.out.append("HTTP/1.1 100 Continue\r\n\r\n") catch {};
                    self.flushConn(conn);
                    if (conn.dying) return;
                }
                self.route(conn);
                if (conn.dying) return;
                continue;
            }

            if (conn.role == .down) return;

            const before = conn.in.size();
            self.pumpBody(conn);
            if (conn.dying) return;
            if (conn.in.size() == before) return;
        }
    }

    fn pumpBody(self: *Edge, conn: *Conn) void {
        if (conn.request.chunked) {
            while (conn.in.size() > 0) {
                const step = conn.dec.feed(conn.in.readable()) catch {
                    self.closeConn(conn);
                    return;
                };
                if (step.consumed > 0) conn.in.consume(step.consumed);
                if (step.body.len > 0) self.deliverBody(conn, step.body);
                if (conn.dying) return;
                if (step.done) {
                    self.endBody(conn);
                    return;
                }
                if (step.consumed == 0 and !step.again) return;
            }
            return;
        }

        var left = conn.body_left orelse 0;
        while (left > 0 and conn.in.size() > 0) {
            const take: usize = @intCast(@min(left, @as(u64, conn.in.size())));
            const slice = conn.in.readable()[0..take];
            self.deliverBody(conn, slice);
            conn.in.consume(take);
            left -= take;
            if (conn.dying) return;
        }
        conn.body_left = left;
        if (left == 0) self.endBody(conn);
    }

    fn deliverBody(self: *Edge, conn: *Conn, bytes: []const u8) void {
        switch (conn.role) {
            .up => {
                const s = conn.session orelse return;
                self.feedUp(s, bytes) catch {
                    self.stats.protocol_errors += 1;
                    self.killSession(s);
                    self.closeConn(conn);
                };
            },
            else => {},
        }
    }

    fn endBody(self: *Edge, conn: *Conn) void {
        switch (conn.role) {
            .up => {
                self.reply(conn, 204, "No Content", "");
                conn.role = .none;
                if (conn.session) |s| {
                    if (s.up == conn) s.up = null;
                }
                conn.session = null;
                conn.head_done = false;
            },
            .none => {
                conn.head_done = false;
            },
            .down => {},
        }
    }

    fn route(self: *Edge, conn: *Conn) void {
        const path = conn.request.path;

        if (std.mem.eql(u8, path, "/proxy/p")) {
            self.reply(conn, 204, "No Content", "");
            conn.head_done = false;
            return;
        }
        if (std.mem.eql(u8, path, "/metrics")) {
            self.serveMetrics(conn);
            return;
        }
        if (std.mem.startsWith(u8, path, "/proxy/u/")) {
            self.attachUp(conn, path["/proxy/u/".len..]);
            return;
        }
        if (std.mem.startsWith(u8, path, "/proxy/d/")) {
            self.attachDown(conn, path["/proxy/d/".len..]);
            return;
        }
        if (std.mem.startsWith(u8, path, "/proxy/c/")) {
            const key = path["/proxy/c/".len..];
            if (self.sessions.get(key)) |s| self.killSession(s);
            self.reply(conn, 204, "No Content", "");
            conn.head_done = false;
            return;
        }

        self.replyAndClose(conn, 404, "Not Found", "no such endpoint");
    }

    const Refusal = error{ BadName, Misdirected, Full, OutOfMemory };

    // A session is created by whichever leg names it first. There is no opening
    // handshake to wait for: the uplink carries the hello as its first frame and
    // the downlink is already open by the time the answer is written to it.
    fn ensureSession(self: *Edge, key: []const u8) Refusal!*Session {
        if (self.sessions.get(key)) |s| return s;
        if (!ids.valid(key)) return error.BadName;
        if (self.cfg.slot != 0 and key[0] != self.cfg.slot) return error.Misdirected;
        if (self.sessions.count() >= self.cfg.max_sessions) return error.Full;

        const s = try self.allocator.create(Session);
        errdefer self.allocator.destroy(s);

        const now = std.time.milliTimestamp();
        s.* = .{
            .edge = self,
            .streams = std.AutoHashMap(u16, *Stream).init(self.allocator),
            .replay = try Ring.init(self.allocator, self.cfg.replay_bytes),
            .out = Buffer.init(self.allocator),
            .wire = Buffer.init(self.allocator),
            .payload = Buffer.init(self.allocator),
            .send_credit = @intCast(self.cfg.session_window),
            .stream_window = self.cfg.stream_window,
            .created = now,
            .last = now,
        };
        @memcpy(s.id[0..], key);

        self.sessions.put(s.id[0..], s) catch |err| {
            self.freeSession(s);
            return err;
        };
        self.stats.sessions_opened += 1;
        log.debug("session {s} created", .{s.id});
        return s;
    }

    fn refuseSession(self: *Edge, conn: *Conn, err: Refusal) void {
        switch (err) {
            error.Misdirected => self.replyAndClose(conn, 421, "Misdirected Request", "wrong slot"),
            error.BadName => self.replyAndClose(conn, 404, "Not Found", "bad session name"),
            else => self.replyAndClose(conn, 503, "Service Unavailable", "no capacity"),
        }
    }

    fn onHello(self: *Edge, s: *Session, payload: []const u8) !void {
        const hello = usp.parseClientHello(payload) catch return error.BadFrame;

        if (hello.session_window != 0) s.send_credit = @intCast(hello.session_window);
        if (hello.stream_window != 0) s.stream_window = hello.stream_window;
        if (s.greeted) return;

        s.greeted = true;
        const resumed = s.down_off > 0 or s.up_consumed > payload.len;

        var buf: [512]u8 = undefined;
        var w = usp.Writer.init(&buf);
        w.u8v(usp.tag_version, usp.version);
        w.str(usp.tag_session, s.id[0..]);
        w.u32v(usp.tag_stream_window, self.cfg.stream_window);
        w.u32v(usp.tag_session_window, self.cfg.session_window);
        w.u32v(usp.tag_features, usp.feature_udp | usp.feature_resume | usp.feature_ipv6 |
            usp.feature_exit_dns | usp.feature_stats | usp.feature_padding);
        w.u64v(usp.tag_time, @intCast(std.time.microTimestamp()));
        w.str(usp.tag_region, self.cfg.region);
        w.str(usp.tag_country, self.cfg.country);
        w.u32v(usp.tag_asn, self.cfg.asn);
        w.u32v(usp.tag_keepalive, self.cfg.keepalive_ms);
        w.u16v(usp.tag_max_streams, @intCast(self.cfg.max_streams));
        w.u32v(usp.tag_replay, @intCast(self.cfg.replay_bytes));
        if (resumed) {
            w.u8v(usp.tag_resumed, 1);
            self.stats.sessions_resumed += 1;
        }
        w.u16v(usp.tag_load, @intCast(@min(1000, self.sessions.count() * 1000 / self.cfg.max_sessions)));

        self.emit(s, .hello_ack, usp.flag_urgent, 0, w.bytes());
    }

    fn attachUp(self: *Edge, conn: *Conn, key: []const u8) void {
        const s = self.ensureSession(key) catch |err| {
            self.refuseSession(conn, err);
            return;
        };
        const from = conn.request.up_offset orelse s.up_consumed;
        if (from > s.up_consumed) {
            self.stats.resume_failures += 1;
            self.replyAndClose(conn, 409, "Conflict", "uplink gap");
            return;
        }

        if (s.up) |old| {
            if (old != conn) self.closeConn(old);
        }
        s.up = conn;
        s.up_skip = s.up_consumed - from;
        s.last = std.time.milliTimestamp();
        conn.session = s;
        conn.role = .up;
        self.stats.legs_up += 1;
        log.debug("session {s} uplink at {d} (skip {d})", .{ s.id, from, s.up_skip });
    }

    fn attachDown(self: *Edge, conn: *Conn, key: []const u8) void {
        const s = self.ensureSession(key) catch |err| {
            self.refuseSession(conn, err);
            return;
        };
        const from = conn.request.down_offset orelse s.down_off;
        if (!s.replay.holds(from)) {
            self.stats.resume_failures += 1;
            self.replyAndClose(conn, 409, "Conflict", "replay window passed");
            return;
        }

        if (s.down) |old| {
            if (old != conn) self.closeConn(old);
        }
        s.down = conn;
        s.last = std.time.milliTimestamp();
        conn.session = s;
        conn.role = .down;
        conn.close_after = true;
        self.stats.legs_down += 1;

        _ = conn.out.append(http.chunked_stream_head) catch {};

        const behind: usize = @intCast(s.replay.pending(from));
        if (behind > 0) {
            const slot = self.scratch[0..@min(behind, self.scratch.len)];
            if (s.replay.since(s.down_off - behind, slot)) |n| {
                s.out.append(slot[0..n]) catch {};
                self.stats.replayed += n;
            }
        }
        self.flushConn(conn);
        if (!conn.dying) self.flushDown(s);
    }

    fn feedUp(self: *Edge, s: *Session, bytes: []const u8) !void {
        var rest = bytes;
        s.last = std.time.milliTimestamp();

        if (s.up_skip > 0) {
            const drop: usize = @intCast(@min(s.up_skip, @as(u64, rest.len)));
            s.up_skip -= drop;
            rest = rest[drop..];
            if (rest.len == 0) return;
        }

        while (rest.len > 0) {
            if (!s.in_body) {
                const need = usp.header_size - s.head_len;
                const take = @min(need, rest.len);
                @memcpy(s.head[s.head_len .. s.head_len + take], rest[0..take]);
                s.head_len += take;
                rest = rest[take..];
                s.up_consumed += take;
                if (s.head_len < usp.header_size) return;

                const header = usp.Header.decode(&s.head);
                if (header.length > usp.max_payload) return error.FrameTooLarge;
                s.want = header.length;
                s.in_body = true;
                s.payload.consume(s.payload.size());
                if (s.want == 0) {
                    try self.onFrame(s, header, &.{});
                    s.in_body = false;
                    s.head_len = 0;
                }
                continue;
            }

            const need = s.want - s.payload.size();
            const take = @min(need, rest.len);
            try s.payload.append(rest[0..take]);
            rest = rest[take..];
            s.up_consumed += take;
            if (s.payload.size() < s.want) return;

            const header = usp.Header.decode(&s.head);
            try self.onFrame(s, header, s.payload.readable());
            s.payload.consume(s.payload.size());
            s.in_body = false;
            s.head_len = 0;
        }
    }

    fn onFrame(self: *Edge, s: *Session, header: usp.Header, raw: []const u8) !void {
        const payload = usp.unpad(header.flags, raw) catch return error.BadFrame;

        switch (header.kind) {
            .hello => try self.onHello(s, payload),
            .open => try self.onOpen(s, header, payload),
            .data => self.onData(s, header.stream, payload),
            .eof => self.onEof(s, header.stream),
            .reset => {
                if (s.streams.get(header.stream)) |st| self.closeStream(st, .none, false);
            },
            .window => {
                if (payload.len < 4) return error.BadFrame;
                const grant: i64 = std.mem.readInt(u32, payload[0..4], .big);
                if (header.stream == 0) {
                    s.send_credit += grant;
                    self.resumeReading(s);
                } else if (s.streams.get(header.stream)) |st| {
                    st.send_credit += grant;
                    if (st.paused) {
                        st.paused = false;
                        self.rearm(&st.reg, linux.EPOLL.IN | linux.EPOLL.RDHUP);
                    }
                }
            },
            .ping => {
                var echo: [24]u8 = undefined;
                const n = @min(payload.len, 16);
                @memcpy(echo[0..n], payload[0..n]);
                std.mem.writeInt(u64, echo[n..][0..8], @intCast(std.time.microTimestamp()), .big);
                self.emit(s, .pong, usp.flag_urgent, 0, echo[0 .. n + 8]);
            },
            .ack => {},
            .settings => {},
            else => {},
        }
    }

    fn onOpen(self: *Edge, s: *Session, header: usp.Header, payload: []const u8) !void {
        if (payload.len < 2) return error.BadFrame;
        if (s.streams.count() >= self.cfg.max_streams) {
            self.refuse(s, header.stream, .too_many_streams);
            return;
        }
        if (s.streams.get(header.stream) != null) return;

        const proto = payload[0];
        const decoded = usp.decodeTarget(payload[1..]) catch {
            self.refuse(s, header.stream, .protocol);
            return;
        };
        const target = decoded.target;

        const st = self.allocator.create(Stream) catch {
            self.refuse(s, header.stream, .internal);
            return;
        };
        st.* = .{
            .id = header.stream,
            .session = s,
            .udp = proto == 2 or header.flags & usp.flag_udp != 0,
            .to_egress = Buffer.init(self.allocator),
            .send_credit = @intCast(if (s.stream_window != 0) s.stream_window else self.cfg.stream_window),
            .port = target.port,
            .deadline = std.time.milliTimestamp() + self.cfg.connect_ms,
        };
        s.streams.put(header.stream, st) catch {
            st.to_egress.deinit();
            self.allocator.destroy(st);
            self.refuse(s, header.stream, .internal);
            return;
        };
        self.stats.streams_opened += 1;

        if (target.address()) |addr| {
            st.addr = addr;
            self.startConnect(st);
            return;
        }

        st.name_len = @min(target.name.len, st.name_buf.len);
        @memcpy(st.name_buf[0..st.name_len], target.name[0..st.name_len]);
        st.state = .resolving;
        st.deadline = std.time.milliTimestamp() + self.cfg.dns_ms;
        self.resolve(st);
    }

    fn resolve(self: *Edge, st: *Stream) void {
        var query: [dns.max_message]u8 = undefined;
        self.dns_id +%= 1;
        if (self.dns_id == 0) self.dns_id = 1;
        st.query = self.dns_id;

        const n = dns.buildQuery(&query, st.query, st.name_buf[0..st.name_len], false) catch {
            self.refuse(st.session, st.id, .dns);
            self.dropStream(st);
            return;
        };
        _ = posix.send(self.dns_reg.fd, query[0..n], 0) catch {
            self.refuse(st.session, st.id, .dns);
            self.dropStream(st);
            return;
        };
        self.pending.put(st.query, st) catch {};
        self.stats.dns_queries += 1;
    }

    fn onDns(self: *Edge) void {
        var buf: [dns.max_message]u8 = undefined;
        while (true) {
            const n = posix.recv(self.dns_reg.fd, &buf, 0) catch return;
            if (n == 0) return;

            const answer = dns.parseAnswer(buf[0..n], 0) catch continue;
            const st = self.pending.get(answer.id) orelse continue;
            _ = self.pending.remove(answer.id);
            if (st.state != .resolving) continue;

            if (answer.address) |addr| {
                st.addr = addr;
                st.addr.setPort(st.port);
                st.deadline = std.time.milliTimestamp() + self.cfg.connect_ms;
                self.startConnect(st);
            } else {
                self.stats.dns_failures += 1;
                self.refuse(st.session, st.id, .dns);
                self.dropStream(st);
            }
        }
    }

    fn startConnect(self: *Edge, st: *Stream) void {
        const kind: u32 = if (st.udp) posix.SOCK.DGRAM else posix.SOCK.STREAM;
        const proto: u32 = if (st.udp) posix.IPPROTO.UDP else posix.IPPROTO.TCP;

        const fd = posix.socket(st.addr.any.family, kind | posix.SOCK.NONBLOCK | posix.SOCK.CLOEXEC, proto) catch {
            self.refuse(st.session, st.id, .internal);
            self.dropStream(st);
            return;
        };
        st.reg.fd = fd;
        if (!st.udp) setNoDelay(fd);

        posix.connect(fd, &st.addr.any, st.addr.getOsSockLen()) catch |err| switch (err) {
            error.WouldBlock => {
                st.state = .connecting;
                self.arm(&st.reg, linux.EPOLL.OUT | linux.EPOLL.RDHUP) catch {
                    posix.close(fd);
                    st.reg.fd = -1;
                    self.refuse(st.session, st.id, .internal);
                    self.dropStream(st);
                };
                return;
            },
            else => {
                posix.close(fd);
                st.reg.fd = -1;
                self.refuse(st.session, st.id, reasonFor(err));
                self.dropStream(st);
                return;
            },
        };
        self.streamReady(st);
    }

    fn streamReady(self: *Edge, st: *Stream) void {
        st.state = .open;
        if (!st.opened) {
            st.opened = true;
            self.emit(st.session, .open_ok, usp.flag_urgent, st.id, &.{});
        }
        if (st.reg.events == 0) {
            self.arm(&st.reg, linux.EPOLL.IN | linux.EPOLL.RDHUP) catch {
                self.closeStream(st, .internal, true);
                return;
            };
        } else {
            self.rearm(&st.reg, linux.EPOLL.IN | linux.EPOLL.RDHUP);
        }
        self.pumpEgressWrite(st);
    }

    fn onEgress(self: *Edge, st: *Stream, events: u32) void {
        if (st.state == .connecting) {
            if (events & (linux.EPOLL.ERR | linux.EPOLL.HUP) != 0) {
                const err = socketError(st.reg.fd);
                self.closeStream(st, reasonForCode(err), true);
                return;
            }
            if (events & linux.EPOLL.OUT != 0) {
                const err = socketError(st.reg.fd);
                if (err != 0) {
                    self.closeStream(st, reasonForCode(err), true);
                    return;
                }
                self.streamReady(st);
                return;
            }
            return;
        }

        if (events & linux.EPOLL.OUT != 0) self.pumpEgressWrite(st);
        if (st.state == .closed) return;
        if (events & linux.EPOLL.IN != 0) self.pumpEgressRead(st);
        if (st.state == .closed) return;
        if (events & (linux.EPOLL.HUP | linux.EPOLL.ERR) != 0) self.closeStream(st, .peer_reset, true);
    }

    fn pumpEgressRead(self: *Edge, st: *Stream) void {
        const s = st.session;
        while (true) {
            if (s.out.size() > out_high_water) {
                st.paused = true;
                self.rearm(&st.reg, linux.EPOLL.RDHUP);
                return;
            }
            const budget = @min(@min(st.send_credit, s.send_credit), @as(i64, read_chunk));
            if (budget <= 0) {
                st.paused = true;
                self.rearm(&st.reg, linux.EPOLL.RDHUP);
                return;
            }

            const slot = self.scratch[0..@intCast(budget)];
            const n = posix.recv(st.reg.fd, slot, 0) catch |err| {
                if (err == error.WouldBlock) return;
                self.closeStream(st, .peer_reset, true);
                return;
            };
            if (n == 0) {
                self.emit(s, .eof, usp.flag_fin, st.id, &.{});
                self.closeStream(st, .none, false);
                return;
            }

            st.send_credit -= @intCast(n);
            s.send_credit -= @intCast(n);
            const flags: u8 = if (st.udp) usp.flag_udp else 0;
            self.emit(s, .data, flags, st.id, slot[0..n]);
            if (n < slot.len) return;
        }
    }

    fn pumpEgressWrite(self: *Edge, st: *Stream) void {
        while (st.to_egress.size() > 0) {
            const chunk = st.to_egress.readable();
            const n = posix.send(st.reg.fd, chunk, 0) catch |err| {
                if (err == error.WouldBlock) {
                    st.want_write = true;
                    self.rearm(&st.reg, st.reg.events | linux.EPOLL.OUT);
                    return;
                }
                self.closeStream(st, .peer_reset, true);
                return;
            };
            st.to_egress.consume(n);
            self.credit(st, n);
            if (n < chunk.len) {
                st.want_write = true;
                self.rearm(&st.reg, st.reg.events | linux.EPOLL.OUT);
                return;
            }
        }

        if (st.want_write) {
            st.want_write = false;
            self.rearm(&st.reg, linux.EPOLL.IN | linux.EPOLL.RDHUP);
        }
        if (st.fin_client) {
            posix.shutdown(st.reg.fd, .send) catch {};
            st.fin_client = false;
        }
    }

    fn credit(self: *Edge, st: *Stream, n: usize) void {
        st.credited += n;
        const s = st.session;
        s.recv_credited += n;

        if (st.credited >= self.cfg.stream_window / 2) {
            var buf: [4]u8 = undefined;
            std.mem.writeInt(u32, &buf, @intCast(st.credited), .big);
            self.emit(s, .window, usp.flag_urgent, st.id, &buf);
            st.credited = 0;
        }
        if (s.recv_credited >= self.cfg.session_window / 2) {
            var buf: [4]u8 = undefined;
            std.mem.writeInt(u32, &buf, @intCast(s.recv_credited), .big);
            self.emit(s, .window, usp.flag_urgent, 0, &buf);
            s.recv_credited = 0;
        }
    }

    fn onData(self: *Edge, s: *Session, id: u16, payload: []const u8) void {
        const st = s.streams.get(id) orelse {
            var buf: [4]u8 = undefined;
            std.mem.writeInt(u32, &buf, @intCast(payload.len), .big);
            self.emit(s, .window, usp.flag_urgent, 0, &buf);
            return;
        };
        st.to_egress.append(payload) catch {
            self.closeStream(st, .internal, true);
            return;
        };
        if (st.state == .open) self.pumpEgressWrite(st);
    }

    fn onEof(self: *Edge, s: *Session, id: u16) void {
        _ = self;
        const st = s.streams.get(id) orelse return;
        st.fin_client = true;
        if (st.state == .open and st.to_egress.size() == 0) {
            posix.shutdown(st.reg.fd, .send) catch {};
            st.fin_client = false;
        }
    }

    fn refuse(self: *Edge, s: *Session, id: u16, reason: usp.Reason) void {
        self.stats.streams_refused += 1;
        const body = [_]u8{@intFromEnum(reason)};
        self.emit(s, .open_err, usp.flag_urgent, id, &body);
    }

    fn dropStream(self: *Edge, st: *Stream) void {
        const s = st.session;
        _ = s.streams.remove(st.id);
        if (st.query != 0) _ = self.pending.remove(st.query);
        if (st.reg.fd >= 0) {
            self.disarm(&st.reg);
            posix.close(st.reg.fd);
        }
        st.state = .closed;
        st.dead_next = self.dead_streams;
        self.dead_streams = st;
    }

    fn closeStream(self: *Edge, st: *Stream, reason: usp.Reason, tell: bool) void {
        if (st.state == .closed) return;
        const s = st.session;
        const id = st.id;
        const opened = st.opened;
        self.dropStream(st);

        if (!tell) return;
        if (!opened) {
            self.refuse(s, id, reason);
            return;
        }
        const body = [_]u8{@intFromEnum(reason)};
        self.emit(s, .reset, usp.flag_urgent, id, &body);
    }

    fn resumeReading(self: *Edge, s: *Session) void {
        var it = s.streams.valueIterator();
        while (it.next()) |slot| {
            const st = slot.*;
            if (st.state != .open or !st.paused) continue;
            if (st.send_credit <= 0 or s.send_credit <= 0) continue;
            st.paused = false;
            self.rearm(&st.reg, linux.EPOLL.IN | linux.EPOLL.RDHUP);
        }
    }

    fn emit(self: *Edge, s: *Session, kind: usp.Type, flags: u8, stream: u16, payload: []const u8) void {
        if (s.dead) return;

        var head: [usp.header_size]u8 = undefined;
        const header = usp.Header{
            .kind = kind,
            .flags = flags,
            .stream = stream,
            .length = @intCast(payload.len),
        };
        header.encode(&head);

        s.replay.append(&head);
        if (payload.len > 0) s.replay.append(payload);
        s.down_off += usp.header_size + payload.len;

        s.out.append(&head) catch {
            self.killSession(s);
            return;
        };
        if (payload.len > 0) {
            s.out.append(payload) catch {
                self.killSession(s);
                return;
            };
        }
        self.flushDown(s);
    }

    fn flushDown(self: *Edge, s: *Session) void {
        const conn = s.down orelse return;
        if (conn.dying) return;

        if (s.wire.size() == 0 and s.out.size() > 0) {
            var head: [24]u8 = undefined;
            const prefix = http.writeChunkHeader(&head, s.out.size());
            s.wire.append(prefix) catch return;
            s.wire.append(s.out.readable()) catch return;
            s.wire.append("\r\n") catch return;
            s.out.consume(s.out.size());
        }

        while (s.wire.size() > 0) {
            const chunk = s.wire.readable();
            const n = posix.send(conn.reg.fd, chunk, linux.MSG.NOSIGNAL) catch |err| {
                if (err == error.WouldBlock) {
                    self.rearm(&conn.reg, linux.EPOLL.IN | linux.EPOLL.OUT | linux.EPOLL.RDHUP);
                    return;
                }
                self.closeConn(conn);
                return;
            };
            s.wire.consume(n);
            self.stats.bytes_out += n;
            if (n < chunk.len) {
                self.rearm(&conn.reg, linux.EPOLL.IN | linux.EPOLL.OUT | linux.EPOLL.RDHUP);
                return;
            }
            if (s.out.size() > 0) {
                var head: [24]u8 = undefined;
                const prefix = http.writeChunkHeader(&head, s.out.size());
                s.wire.append(prefix) catch return;
                s.wire.append(s.out.readable()) catch return;
                s.wire.append("\r\n") catch return;
                s.out.consume(s.out.size());
            }
        }

        self.rearm(&conn.reg, linux.EPOLL.IN | linux.EPOLL.RDHUP);
        self.resumeReading(s);
    }

    fn reply(self: *Edge, conn: *Conn, code: u16, phrase: []const u8, body: []const u8) void {
        var head: [512]u8 = undefined;
        const text = http.simple(&head, code, phrase, body, false);
        _ = conn.out.append(text) catch {};
        self.flushConn(conn);
    }

    fn replyAndClose(self: *Edge, conn: *Conn, code: u16, phrase: []const u8, body: []const u8) void {
        var head: [512]u8 = undefined;
        const text = http.simple(&head, code, phrase, body, true);
        _ = conn.out.append(text) catch {};
        conn.close_after = true;
        self.flushConn(conn);
    }

    fn flushConn(self: *Edge, conn: *Conn) void {
        while (conn.out.size() > 0) {
            const chunk = conn.out.readable();
            const n = posix.send(conn.reg.fd, chunk, linux.MSG.NOSIGNAL) catch |err| {
                if (err == error.WouldBlock) {
                    self.rearm(&conn.reg, linux.EPOLL.IN | linux.EPOLL.OUT | linux.EPOLL.RDHUP);
                    return;
                }
                self.closeConn(conn);
                return;
            };
            conn.out.consume(n);
            self.stats.bytes_out += n;
            if (n < chunk.len) {
                self.rearm(&conn.reg, linux.EPOLL.IN | linux.EPOLL.OUT | linux.EPOLL.RDHUP);
                return;
            }
        }
        if (conn.close_after and conn.role != .down) {
            self.closeConn(conn);
            return;
        }
        self.rearm(&conn.reg, linux.EPOLL.IN | linux.EPOLL.RDHUP);
    }

    fn serveMetrics(self: *Edge, conn: *Conn) void {
        var body: [2048]u8 = undefined;
        const text = std.fmt.bufPrint(&body,
            \\# TYPE unsafie_edge_sessions_opened_total counter
            \\unsafie_edge_sessions_opened_total {d}
            \\# TYPE unsafie_edge_sessions_resumed_total counter
            \\unsafie_edge_sessions_resumed_total {d}
            \\# TYPE unsafie_edge_sessions gauge
            \\unsafie_edge_sessions {d}
            \\# TYPE unsafie_edge_legs_total counter
            \\unsafie_edge_legs_total{{direction="up"}} {d}
            \\unsafie_edge_legs_total{{direction="down"}} {d}
            \\# TYPE unsafie_edge_streams_total counter
            \\unsafie_edge_streams_total {d}
            \\# TYPE unsafie_edge_streams_refused_total counter
            \\unsafie_edge_streams_refused_total {d}
            \\# TYPE unsafie_edge_dns_total counter
            \\unsafie_edge_dns_total {d}
            \\# TYPE unsafie_edge_dns_failures_total counter
            \\unsafie_edge_dns_failures_total {d}
            \\# TYPE unsafie_edge_bytes_total counter
            \\unsafie_edge_bytes_total{{direction="in"}} {d}
            \\unsafie_edge_bytes_total{{direction="out"}} {d}
            \\# TYPE unsafie_edge_replayed_bytes_total counter
            \\unsafie_edge_replayed_bytes_total {d}
            \\# TYPE unsafie_edge_resume_failures_total counter
            \\unsafie_edge_resume_failures_total {d}
            \\# TYPE unsafie_edge_protocol_errors_total counter
            \\unsafie_edge_protocol_errors_total {d}
            \\
        , .{
            self.stats.sessions_opened,
            self.stats.sessions_resumed,
            self.sessions.count(),
            self.stats.legs_up,
            self.stats.legs_down,
            self.stats.streams_opened,
            self.stats.streams_refused,
            self.stats.dns_queries,
            self.stats.dns_failures,
            self.stats.bytes_in,
            self.stats.bytes_out,
            self.stats.replayed,
            self.stats.resume_failures,
            self.stats.protocol_errors,
        }) catch "";

        var head: [4096]u8 = undefined;
        const response = http.simple(&head, 200, "OK", text, false);
        _ = conn.out.append(response) catch {};
        conn.head_done = false;
        self.flushConn(conn);
    }

    fn killSession(self: *Edge, s: *Session) void {
        if (s.dead) return;
        s.dead = true;

        const body = [_]u8{@intFromEnum(usp.Reason.session_gone)};
        if (s.down) |conn| {
            _ = conn;
            var head: [usp.header_size]u8 = undefined;
            const header = usp.Header{ .kind = .goaway, .flags = usp.flag_urgent, .stream = 0, .length = 1 };
            header.encode(&head);
            s.out.append(&head) catch {};
            s.out.append(&body) catch {};
            self.flushDown(s);
        }

        _ = self.sessions.remove(s.id[0..]);
        if (s.up) |conn| {
            conn.session = null;
            self.closeConn(conn);
        }
        if (s.down) |conn| {
            conn.session = null;
            self.closeConn(conn);
        }
        s.dead_next = self.dead_sessions;
        self.dead_sessions = s;
    }

    fn freeSession(self: *Edge, s: *Session) void {
        var it = s.streams.valueIterator();
        while (it.next()) |slot| {
            const st = slot.*;
            if (st.query != 0) _ = self.pending.remove(st.query);
            if (st.reg.fd >= 0) {
                self.disarm(&st.reg);
                posix.close(st.reg.fd);
            }
            st.to_egress.deinit();
            self.allocator.destroy(st);
        }
        s.streams.deinit();
        s.replay.deinit();
        s.out.deinit();
        s.wire.deinit();
        s.payload.deinit();
        self.allocator.destroy(s);
    }

    fn tick(self: *Edge, now: i64) void {
        var expired: [64][ids.id_len]u8 = undefined;
        var count: usize = 0;

        var it = self.sessions.iterator();
        while (it.next()) |entry| {
            const s = entry.value_ptr.*;
            if (now - s.last > self.cfg.idle_ms and s.up == null and s.down == null) {
                if (count < expired.len) {
                    expired[count] = s.id;
                    count += 1;
                }
                continue;
            }
            self.expireStreams(s, now);
        }

        for (expired[0..count]) |key| {
            if (self.sessions.get(key[0..])) |s| self.killSession(s);
        }
    }

    fn expireStreams(self: *Edge, s: *Session, now: i64) void {
        var late: [32]*Stream = undefined;
        var count: usize = 0;

        var it = s.streams.valueIterator();
        while (it.next()) |slot| {
            const st = slot.*;
            if (st.state == .open or st.deadline == 0 or now < st.deadline) continue;
            if (count < late.len) {
                late[count] = st;
                count += 1;
            }
        }
        for (late[0..count]) |st| {
            const reason: usp.Reason = if (st.state == .resolving) .dns else .timeout;
            self.closeStream(st, reason, true);
        }
    }
};

fn setNoDelay(fd: posix.fd_t) void {
    const one: c_int = 1;
    posix.setsockopt(fd, posix.IPPROTO.TCP, posix.TCP.NODELAY, std.mem.asBytes(&one)) catch {};
}

fn socketError(fd: posix.fd_t) u32 {
    var value: u32 = 0;
    var len: posix.socklen_t = @sizeOf(u32);
    const rc = linux.getsockopt(fd, posix.SOL.SOCKET, posix.SO.ERROR, @ptrCast(&value), &len);
    if (posix.errno(rc) != .SUCCESS) return @intFromEnum(linux.E.IO);
    return value;
}

fn reasonForCode(code: u32) usp.Reason {
    return switch (@as(linux.E, @enumFromInt(code))) {
        .SUCCESS => .none,
        .CONNREFUSED => .refused,
        .HOSTUNREACH => .host_unreachable,
        .NETUNREACH => .net_unreachable,
        .TIMEDOUT => .timeout,
        .CONNRESET, .PIPE => .peer_reset,
        .ACCES, .PERM => .policy,
        else => .internal,
    };
}

fn reasonFor(err: anyerror) usp.Reason {
    return switch (err) {
        error.ConnectionRefused => .refused,
        error.NetworkUnreachable => .net_unreachable,
        error.ConnectionTimedOut => .timeout,
        error.ConnectionResetByPeer => .peer_reset,
        error.PermissionDenied => .policy,
        else => .internal,
    };
}

fn openListener(addr: std.net.Address) !posix.fd_t {
    const fd = try posix.socket(
        addr.any.family,
        posix.SOCK.STREAM | posix.SOCK.NONBLOCK | posix.SOCK.CLOEXEC,
        posix.IPPROTO.TCP,
    );
    errdefer posix.close(fd);

    const one: c_int = 1;
    try posix.setsockopt(fd, posix.SOL.SOCKET, posix.SO.REUSEADDR, std.mem.asBytes(&one));
    posix.setsockopt(fd, posix.SOL.SOCKET, posix.SO.REUSEPORT, std.mem.asBytes(&one)) catch {};

    try posix.bind(fd, &addr.any, addr.getOsSockLen());
    try posix.listen(fd, 1024);
    return fd;
}
