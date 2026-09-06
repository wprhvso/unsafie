const std = @import("std");

pub const max_message: usize = 1232;

pub fn buildQuery(out: []u8, id: u16, name: []const u8, want_v6: bool) !usize {
    if (name.len == 0 or name.len > 253) return error.BadName;
    var n: usize = 0;
    if (out.len < 12 + name.len + 6) return error.NoSpace;

    std.mem.writeInt(u16, out[0..2], id, .big);
    std.mem.writeInt(u16, out[2..4], 0x0100, .big);
    std.mem.writeInt(u16, out[4..6], 1, .big);
    std.mem.writeInt(u16, out[6..8], 0, .big);
    std.mem.writeInt(u16, out[8..10], 0, .big);
    std.mem.writeInt(u16, out[10..12], 0, .big);
    n = 12;

    var it = std.mem.splitScalar(u8, name, '.');
    while (it.next()) |label| {
        if (label.len == 0) continue;
        if (label.len > 63) return error.BadName;
        out[n] = @intCast(label.len);
        n += 1;
        @memcpy(out[n .. n + label.len], label);
        n += label.len;
    }
    out[n] = 0;
    n += 1;

    std.mem.writeInt(u16, out[n..][0..2], if (want_v6) 28 else 1, .big);
    n += 2;
    std.mem.writeInt(u16, out[n..][0..2], 1, .big);
    n += 2;
    return n;
}

fn skipName(msg: []const u8, start: usize) !usize {
    var i = start;
    while (i < msg.len) {
        const len = msg[i];
        if (len == 0) return i + 1;
        if (len & 0xC0 == 0xC0) {
            if (i + 2 > msg.len) return error.Malformed;
            return i + 2;
        }
        i += 1 + @as(usize, len);
    }
    return error.Malformed;
}

pub const Answer = struct {
    id: u16,
    rcode: u4,
    address: ?std.net.Address,
    ttl: u32,
};

pub fn parseAnswer(msg: []const u8, port: u16) !Answer {
    if (msg.len < 12) return error.Malformed;
    const id = std.mem.readInt(u16, msg[0..2], .big);
    const flags = std.mem.readInt(u16, msg[2..4], .big);
    const qd = std.mem.readInt(u16, msg[4..6], .big);
    const an = std.mem.readInt(u16, msg[6..8], .big);
    const rcode: u4 = @truncate(flags & 0x000F);

    var out = Answer{ .id = id, .rcode = rcode, .address = null, .ttl = 60 };
    if (rcode != 0) return out;

    var pos: usize = 12;
    var q: u16 = 0;
    while (q < qd) : (q += 1) {
        pos = try skipName(msg, pos);
        if (pos + 4 > msg.len) return error.Malformed;
        pos += 4;
    }

    var a: u16 = 0;
    while (a < an) : (a += 1) {
        pos = try skipName(msg, pos);
        if (pos + 10 > msg.len) return error.Malformed;
        const rtype = std.mem.readInt(u16, msg[pos..][0..2], .big);
        const ttl = std.mem.readInt(u32, msg[pos + 4 ..][0..4], .big);
        const rdlen = std.mem.readInt(u16, msg[pos + 8 ..][0..2], .big);
        pos += 10;
        if (pos + rdlen > msg.len) return error.Malformed;

        if (rtype == 1 and rdlen == 4 and out.address == null) {
            out.address = std.net.Address.initIp4(msg[pos..][0..4].*, port);
            out.ttl = ttl;
        } else if (rtype == 28 and rdlen == 16 and out.address == null) {
            out.address = std.net.Address.initIp6(msg[pos..][0..16].*, port, 0, 0);
            out.ttl = ttl;
        }
        pos += rdlen;
    }
    return out;
}

test "query and answer round trip" {
    var buf: [512]u8 = undefined;
    const n = try buildQuery(&buf, 0x1234, "example.com", false);
    try std.testing.expect(n > 12);
    try std.testing.expectEqual(@as(u16, 0x1234), std.mem.readInt(u16, buf[0..2], .big));
}
