const std = @import("std");

pub const id_len: usize = 22;

const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";

fn member(c: u8) bool {
    return std.mem.indexOfScalar(u8, alphabet, c) != null;
}

// The client names its own sessions, which is what lets both legs leave at the
// same moment: neither has to wait to be told where to go. The exit therefore
// checks the shape and nothing else — the name was already carried past the
// bearer token nginx verifies, and the 126 bits of randomness inside it are
// what keep one client from landing in another's session.
pub fn valid(text: []const u8) bool {
    if (text.len != id_len) return false;
    for (text) |c| {
        if (!member(c)) return false;
    }
    return true;
}

test "session names are checked by shape" {
    try std.testing.expect(valid("aBcDeFgHiJkLmNoPqRsTuV"));
    try std.testing.expect(!valid("too-short"));
    try std.testing.expect(!valid("aBcDeFgHiJkLmNoPqRsTu*"));
    try std.testing.expect(!valid("aBcDeFgHiJkLmNoPqRsTuVW"));
}
