const std = @import("std");

pub const max_head: usize = 16 * 1024;

pub const Method = enum { get, post, head, other };

pub const Request = struct {
    method: Method = .other,
    path: []const u8 = &.{},
    chunked: bool = false,
    content_length: ?u64 = null,
    keep_alive: bool = true,
    expect_continue: bool = false,
    up_offset: ?u64 = null,
    down_offset: ?u64 = null,
    wire: []const u8 = &.{},
    authorization: []const u8 = &.{},
};

pub const Parsed = struct {
    request: Request,
    head_len: usize,
};

fn eqlIgnoreCase(a: []const u8, b: []const u8) bool {
    return std.ascii.eqlIgnoreCase(a, b);
}

fn trim(s: []const u8) []const u8 {
    return std.mem.trim(u8, s, " \t");
}

pub fn parse(buf: []const u8) !?Parsed {
    const end = std.mem.indexOf(u8, buf, "\r\n\r\n") orelse {
        if (buf.len > max_head) return error.HeadTooLarge;
        return null;
    };
    const head = buf[0..end];
    var lines = std.mem.splitSequence(u8, head, "\r\n");

    const start = lines.next() orelse return error.BadRequest;
    var parts = std.mem.splitScalar(u8, start, ' ');
    const method_text = parts.next() orelse return error.BadRequest;
    const path = parts.next() orelse return error.BadRequest;
    const proto = parts.next() orelse return error.BadRequest;
    if (!std.mem.eql(u8, proto, "HTTP/1.1") and !std.mem.eql(u8, proto, "HTTP/1.0")) {
        return error.BadVersion;
    }

    var out = Request{
        .path = path,
        .keep_alive = std.mem.eql(u8, proto, "HTTP/1.1"),
    };
    out.method = if (eqlIgnoreCase(method_text, "GET"))
        .get
    else if (eqlIgnoreCase(method_text, "POST"))
        .post
    else if (eqlIgnoreCase(method_text, "HEAD"))
        .head
    else
        .other;

    while (lines.next()) |line| {
        if (line.len == 0) continue;
        const colon = std.mem.indexOfScalar(u8, line, ':') orelse continue;
        const name = trim(line[0..colon]);
        const value = trim(line[colon + 1 ..]);

        if (eqlIgnoreCase(name, "content-length")) {
            out.content_length = std.fmt.parseInt(u64, value, 10) catch return error.BadRequest;
        } else if (eqlIgnoreCase(name, "transfer-encoding")) {
            if (std.ascii.indexOfIgnoreCase(value, "chunked") != null) out.chunked = true;
        } else if (eqlIgnoreCase(name, "connection")) {
            if (std.ascii.indexOfIgnoreCase(value, "close") != null) out.keep_alive = false;
            if (std.ascii.indexOfIgnoreCase(value, "keep-alive") != null) out.keep_alive = true;
        } else if (eqlIgnoreCase(name, "expect")) {
            if (std.ascii.indexOfIgnoreCase(value, "100-continue") != null) out.expect_continue = true;
        } else if (eqlIgnoreCase(name, "x-usp-up")) {
            out.up_offset = std.fmt.parseInt(u64, value, 10) catch null;
        } else if (eqlIgnoreCase(name, "x-usp-down")) {
            out.down_offset = std.fmt.parseInt(u64, value, 10) catch null;
        } else if (eqlIgnoreCase(name, "x-usp-wire")) {
            out.wire = value;
        } else if (eqlIgnoreCase(name, "authorization")) {
            out.authorization = value;
        }
    }

    return Parsed{ .request = out, .head_len = end + 4 };
}

pub const ChunkState = enum { size, data, data_crlf, trailer, done };

pub const ChunkDecoder = struct {
    state: ChunkState = .size,
    remaining: u64 = 0,
    line: [32]u8 = undefined,
    line_len: usize = 0,

    pub const Step = struct {
        consumed: usize,
        body: []const u8 = &.{},
        done: bool = false,
        again: bool = false,
    };

    pub fn feed(self: *ChunkDecoder, input: []const u8) !Step {
        switch (self.state) {
            .done => return .{ .consumed = 0, .done = true },

            .size => {
                var i: usize = 0;
                while (i < input.len) : (i += 1) {
                    const c = input[i];
                    if (c == '\n') {
                        const text = std.mem.trim(u8, self.line[0..self.line_len], " \r\t");
                        const cut = std.mem.indexOfScalar(u8, text, ';') orelse text.len;
                        const size = std.fmt.parseInt(u64, text[0..cut], 16) catch return error.BadChunk;
                        self.line_len = 0;
                        self.remaining = size;
                        self.state = if (size == 0) .trailer else .data;
                        return .{ .consumed = i + 1, .again = true };
                    }
                    if (self.line_len == self.line.len) return error.BadChunk;
                    self.line[self.line_len] = c;
                    self.line_len += 1;
                }
                return .{ .consumed = input.len };
            },

            .data => {
                if (input.len == 0) return .{ .consumed = 0 };
                const n: usize = @intCast(@min(self.remaining, @as(u64, input.len)));
                self.remaining -= n;
                if (self.remaining == 0) self.state = .data_crlf;
                return .{ .consumed = n, .body = input[0..n], .again = true };
            },

            .data_crlf => {
                var i: usize = 0;
                while (i < input.len) : (i += 1) {
                    if (input[i] == '\n') {
                        self.state = .size;
                        return .{ .consumed = i + 1, .again = true };
                    }
                }
                return .{ .consumed = input.len };
            },

            .trailer => {
                var i: usize = 0;
                while (i < input.len) : (i += 1) {
                    const c = input[i];
                    if (c == '\n') {
                        const text = std.mem.trim(u8, self.line[0..self.line_len], " \r\t");
                        self.line_len = 0;
                        if (text.len == 0) {
                            self.state = .done;
                            return .{ .consumed = i + 1, .done = true };
                        }
                        return .{ .consumed = i + 1, .again = true };
                    }
                    if (self.line_len < self.line.len) {
                        self.line[self.line_len] = c;
                        self.line_len += 1;
                    }
                }
                return .{ .consumed = input.len };
            },
        }
    }
};

pub fn writeChunkHeader(out: []u8, n: usize) []const u8 {
    return std.fmt.bufPrint(out, "{x}\r\n", .{n}) catch unreachable;
}

pub const status_ok = "HTTP/1.1 200 OK\r\n";
pub const chunked_stream_head =
    "HTTP/1.1 200 OK\r\n" ++
    "Content-Type: application/octet-stream\r\n" ++
    "Cache-Control: no-store\r\n" ++
    "X-Accel-Buffering: no\r\n" ++
    "Transfer-Encoding: chunked\r\n" ++
    "Connection: close\r\n\r\n";

pub fn simple(out: []u8, code: u16, phrase: []const u8, body: []const u8, close: bool) []const u8 {
    return std.fmt.bufPrint(out,
        "HTTP/1.1 {d} {s}\r\n" ++
            "Content-Type: text/plain; charset=utf-8\r\n" ++
            "Content-Length: {d}\r\n" ++
            "Cache-Control: no-store\r\n" ++
            "Connection: {s}\r\n\r\n{s}",
        .{ code, phrase, body.len, if (close) "close" else "keep-alive", body },
    ) catch out[0..0];
}

pub fn binary(out: []u8, body: []const u8, close: bool) []const u8 {
    return std.fmt.bufPrint(out,
        "HTTP/1.1 200 OK\r\n" ++
            "Content-Type: application/octet-stream\r\n" ++
            "Content-Length: {d}\r\n" ++
            "Cache-Control: no-store\r\n" ++
            "Alt-Svc: h3=\":443\"; ma=86400\r\n" ++
            "Connection: {s}\r\n\r\n{s}",
        .{ body.len, if (close) "close" else "keep-alive", body },
    ) catch out[0..0];
}

test "request parsing" {
    const raw = "POST /proxy/u/abc HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: chunked\r\nX-Usp-Up: 4096\r\n\r\n";
    const got = (try parse(raw)).?;
    try std.testing.expectEqual(Method.post, got.request.method);
    try std.testing.expect(got.request.chunked);
    try std.testing.expectEqual(@as(u64, 4096), got.request.up_offset.?);
}

test "chunked decoding" {
    var dec = ChunkDecoder{};
    const input = "5\r\nhello\r\n0\r\n\r\n";
    var pos: usize = 0;
    var seen: usize = 0;
    while (pos < input.len) {
        const step = try dec.feed(input[pos..]);
        pos += step.consumed;
        seen += step.body.len;
        if (step.done) break;
        if (step.consumed == 0 and !step.again) break;
    }
    try std.testing.expectEqual(@as(usize, 5), seen);
    try std.testing.expectEqual(ChunkState.done, dec.state);
}
