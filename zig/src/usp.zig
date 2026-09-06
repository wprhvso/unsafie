const std = @import("std");

pub const version: u8 = 1;
pub const header_size: usize = 8;
pub const max_payload: usize = 1 << 20;

pub const Type = enum(u8) {
    hello_ack = 0x01,
    open = 0x02,
    open_ok = 0x03,
    open_err = 0x04,
    data = 0x05,
    eof = 0x06,
    reset = 0x07,
    window = 0x08,
    dgram = 0x09,
    ping = 0x0A,
    pong = 0x0B,
    settings = 0x0C,
    goaway = 0x0D,
    stats = 0x0E,
    ack = 0x0F,
    _,
};

pub const flag_padded: u8 = 1 << 0;
pub const flag_fin: u8 = 1 << 1;
pub const flag_udp: u8 = 1 << 2;
pub const flag_urgent: u8 = 1 << 3;

pub const Reason = enum(u8) {
    none = 0,
    refused = 1,
    host_unreachable = 2,
    net_unreachable = 3,
    timeout = 4,
    dns = 5,
    policy = 6,
    geo_blocked = 7,
    rate_limited = 8,
    internal = 9,
    idle = 10,
    session_gone = 11,
    protocol = 12,
    peer_reset = 13,
    handshake_stall = 14,
    shutdown = 15,
    overloaded = 16,
    too_many_streams = 17,
    unauthorized = 18,
    edge_unreachable = 19,
};

pub const Header = struct {
    kind: Type,
    flags: u8,
    stream: u16,
    length: u32,

    pub fn decode(bytes: *const [header_size]u8) Header {
        return .{
            .kind = @enumFromInt(bytes[0]),
            .flags = bytes[1],
            .stream = std.mem.readInt(u16, bytes[2..4], .big),
            .length = std.mem.readInt(u32, bytes[4..8], .big),
        };
    }

    pub fn encode(self: Header, out: *[header_size]u8) void {
        out[0] = @intFromEnum(self.kind);
        out[1] = self.flags;
        std.mem.writeInt(u16, out[2..4], self.stream, .big);
        std.mem.writeInt(u32, out[4..8], self.length, .big);
    }
};

pub fn unpad(flags: u8, payload: []const u8) ![]const u8 {
    if (flags & flag_padded == 0) return payload;
    if (payload.len < 2) return error.BadPadding;
    const pad = std.mem.readInt(u16, payload[payload.len - 2 ..][0..2], .big);
    if (@as(usize, pad) + 2 > payload.len) return error.BadPadding;
    return payload[0 .. payload.len - pad - 2];
}

pub const AddrKind = enum(u8) { ipv4 = 1, ipv6 = 2, domain = 3 };

pub const Target = struct {
    kind: AddrKind,
    ip: [16]u8 = @splat(0),
    name: []const u8 = &.{},
    port: u16 = 0,

    pub fn address(self: Target) ?std.net.Address {
        return switch (self.kind) {
            .ipv4 => std.net.Address.initIp4(self.ip[0..4].*, self.port),
            .ipv6 => std.net.Address.initIp6(self.ip, self.port, 0, 0),
            .domain => null,
        };
    }
};

pub fn decodeTarget(bytes: []const u8) !struct { target: Target, rest: []const u8 } {
    if (bytes.len < 1) return error.BadAddress;
    const kind: AddrKind = switch (bytes[0]) {
        1 => .ipv4,
        2 => .ipv6,
        3 => .domain,
        else => return error.BadAddress,
    };
    var body = bytes[1..];
    var out = Target{ .kind = kind };

    switch (kind) {
        .ipv4 => {
            if (body.len < 4) return error.BadAddress;
            @memcpy(out.ip[0..4], body[0..4]);
            body = body[4..];
        },
        .ipv6 => {
            if (body.len < 16) return error.BadAddress;
            @memcpy(out.ip[0..16], body[0..16]);
            body = body[16..];
        },
        .domain => {
            if (body.len < 1) return error.BadAddress;
            const n = body[0];
            if (body.len < 1 + @as(usize, n)) return error.BadAddress;
            out.name = body[1 .. 1 + @as(usize, n)];
            body = body[1 + @as(usize, n) ..];
        },
    }

    if (body.len < 2) return error.BadAddress;
    out.port = std.mem.readInt(u16, body[0..2], .big);
    return .{ .target = out, .rest = body[2..] };
}

pub const tag_version: u16 = 0x0001;
pub const tag_nonce: u16 = 0x0002;
pub const tag_stream_window: u16 = 0x0003;
pub const tag_session_window: u16 = 0x0004;
pub const tag_features: u16 = 0x0005;
pub const tag_time: u16 = 0x0006;
pub const tag_resume: u16 = 0x0007;
pub const tag_down_off: u16 = 0x0008;
pub const tag_label: u16 = 0x0009;
pub const tag_wire: u16 = 0x000A;

pub const tag_session: u16 = 0x8001;
pub const tag_region: u16 = 0x8002;
pub const tag_country: u16 = 0x8003;
pub const tag_asn: u16 = 0x8004;
pub const tag_exit_ip: u16 = 0x8005;
pub const tag_keepalive: u16 = 0x8006;
pub const tag_max_streams: u16 = 0x8007;
pub const tag_replay: u16 = 0x8008;
pub const tag_resumed: u16 = 0x8009;
pub const tag_load: u16 = 0x800A;

pub const feature_udp: u32 = 1 << 0;
pub const feature_resume: u32 = 1 << 1;
pub const feature_ipv6: u32 = 1 << 2;
pub const feature_happy_eyeballs: u32 = 1 << 3;
pub const feature_exit_dns: u32 = 1 << 4;
pub const feature_stats: u32 = 1 << 5;
pub const feature_padding: u32 = 1 << 6;

pub const ClientHello = struct {
    version: u8 = 0,
    stream_window: u32 = 0,
    session_window: u32 = 0,
    features: u32 = 0,
    resume_session: []const u8 = &.{},
    resume_down_at: u64 = 0,
    label: []const u8 = &.{},
    wire: []const u8 = &.{},
};

pub fn parseClientHello(body: []const u8) !ClientHello {
    var out = ClientHello{};
    var rest = body;
    while (rest.len > 0) {
        if (rest.len < 4) return error.BadHello;
        const tag = std.mem.readInt(u16, rest[0..2], .big);
        const len = std.mem.readInt(u16, rest[2..4], .big);
        if (rest.len < 4 + @as(usize, len)) return error.BadHello;
        const value = rest[4 .. 4 + @as(usize, len)];
        switch (tag) {
            tag_version => if (value.len == 1) {
                out.version = value[0];
            },
            tag_stream_window => if (value.len == 4) {
                out.stream_window = std.mem.readInt(u32, value[0..4], .big);
            },
            tag_session_window => if (value.len == 4) {
                out.session_window = std.mem.readInt(u32, value[0..4], .big);
            },
            tag_features => if (value.len == 4) {
                out.features = std.mem.readInt(u32, value[0..4], .big);
            },
            tag_resume => out.resume_session = value,
            tag_down_off => if (value.len == 8) {
                out.resume_down_at = std.mem.readInt(u64, value[0..8], .big);
            },
            tag_label => out.label = value,
            tag_wire => out.wire = value,
            else => {},
        }
        rest = rest[4 + @as(usize, len) ..];
    }
    if (out.version != version) return error.BadVersion;
    return out;
}

pub const Writer = struct {
    buf: []u8,
    len: usize = 0,

    pub fn init(buf: []u8) Writer {
        return .{ .buf = buf };
    }

    fn put(self: *Writer, tag: u16, value: []const u8) void {
        if (self.len + 4 + value.len > self.buf.len) return;
        std.mem.writeInt(u16, self.buf[self.len..][0..2], tag, .big);
        std.mem.writeInt(u16, self.buf[self.len + 2 ..][0..2], @intCast(value.len), .big);
        @memcpy(self.buf[self.len + 4 ..][0..value.len], value);
        self.len += 4 + value.len;
    }

    pub fn u8v(self: *Writer, tag: u16, v: u8) void {
        self.put(tag, &[_]u8{v});
    }

    pub fn u16v(self: *Writer, tag: u16, v: u16) void {
        var tmp: [2]u8 = undefined;
        std.mem.writeInt(u16, &tmp, v, .big);
        self.put(tag, &tmp);
    }

    pub fn u32v(self: *Writer, tag: u16, v: u32) void {
        var tmp: [4]u8 = undefined;
        std.mem.writeInt(u32, &tmp, v, .big);
        self.put(tag, &tmp);
    }

    pub fn u64v(self: *Writer, tag: u16, v: u64) void {
        var tmp: [8]u8 = undefined;
        std.mem.writeInt(u64, &tmp, v, .big);
        self.put(tag, &tmp);
    }

    pub fn str(self: *Writer, tag: u16, v: []const u8) void {
        if (v.len == 0) return;
        self.put(tag, v);
    }

    pub fn bytes(self: *Writer) []const u8 {
        return self.buf[0..self.len];
    }
};

test "frame header round trip" {
    var raw: [header_size]u8 = undefined;
    const h = Header{ .kind = .data, .flags = flag_fin, .stream = 4097, .length = 1234 };
    h.encode(&raw);
    const back = Header.decode(&raw);
    try std.testing.expectEqual(h.stream, back.stream);
    try std.testing.expectEqual(h.length, back.length);
    try std.testing.expectEqual(h.flags, back.flags);
    try std.testing.expectEqual(@intFromEnum(h.kind), @intFromEnum(back.kind));
}

test "target decoding" {
    const raw = [_]u8{ 1, 93, 184, 216, 34, 0x01, 0xBB };
    const got = try decodeTarget(&raw);
    try std.testing.expectEqual(@as(u16, 443), got.target.port);
    try std.testing.expectEqual(AddrKind.ipv4, got.target.kind);
}
