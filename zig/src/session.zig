const std = @import("std");

pub const id_bytes: usize = 16;
pub const id_len: usize = 22;

const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";

pub const Minter = struct {
    key: [16]u8,
    counter: u64 = 0,

    pub fn init() Minter {
        var key: [16]u8 = undefined;
        std.crypto.random.bytes(&key);
        return .{ .key = key };
    }

    pub fn mint(self: *Minter, out: *[id_len]u8) void {
        var raw: [id_bytes]u8 = undefined;
        std.crypto.random.bytes(raw[0..8]);
        self.counter +%= 1;
        std.mem.writeInt(u64, raw[0..8], std.mem.readInt(u64, raw[0..8], .big) ^ self.counter, .big);
        const mac = std.hash.SipHash64(2, 4).toInt(raw[0..8], &self.key);
        std.mem.writeInt(u64, raw[8..16], mac, .big);
        encode(&raw, out);
    }

    pub fn valid(self: *const Minter, text: []const u8) bool {
        if (text.len != id_len) return false;
        var raw: [id_bytes]u8 = undefined;
        if (!decode(text, &raw)) return false;
        const mac = std.hash.SipHash64(2, 4).toInt(raw[0..8], &self.key);
        return mac == std.mem.readInt(u64, raw[8..16], .big);
    }
};

pub fn encode(raw: *const [id_bytes]u8, out: *[id_len]u8) void {
    var acc: u32 = 0;
    var bits: u5 = 0;
    var o: usize = 0;
    for (raw) |b| {
        acc = (acc << 8) | b;
        bits +%= 8;
        while (bits >= 6) {
            bits -= 6;
            out[o] = alphabet[(acc >> bits) & 63];
            o += 1;
            if (o == id_len) return;
        }
    }
    if (o < id_len) {
        out[o] = alphabet[(acc << (6 - bits)) & 63];
    }
}

fn value(c: u8) ?u8 {
    return switch (c) {
        'A'...'Z' => c - 'A',
        'a'...'z' => c - 'a' + 26,
        '0'...'9' => c - '0' + 52,
        '-' => 62,
        '_' => 63,
        else => null,
    };
}

pub fn decode(text: []const u8, out: *[id_bytes]u8) bool {
    if (text.len != id_len) return false;
    var acc: u32 = 0;
    var bits: u5 = 0;
    var o: usize = 0;
    for (text) |c| {
        const v = value(c) orelse return false;
        acc = (acc << 6) | v;
        bits +%= 6;
        if (bits >= 8) {
            bits -= 8;
            if (o < id_bytes) {
                out[o] = @truncate(acc >> bits);
                o += 1;
            }
        }
    }
    return o == id_bytes;
}

test "session ids round trip and authenticate" {
    var minter = Minter.init();
    var id: [id_len]u8 = undefined;
    minter.mint(&id);
    try std.testing.expect(minter.valid(&id));

    var broken = id;
    broken[3] = if (broken[3] == 'A') 'B' else 'A';
    try std.testing.expect(!minter.valid(&broken));
}
