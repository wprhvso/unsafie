const std = @import("std");

pub var verbose: bool = false;

pub fn info(comptime fmt: []const u8, args: anytype) void {
    std.debug.print("[edge] " ++ fmt ++ "\n", args);
}

pub fn warn(comptime fmt: []const u8, args: anytype) void {
    std.debug.print("[edge] warning: " ++ fmt ++ "\n", args);
}

pub fn debug(comptime fmt: []const u8, args: anytype) void {
    if (!verbose) return;
    std.debug.print("[edge] debug: " ++ fmt ++ "\n", args);
}
