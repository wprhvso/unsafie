const std = @import("std");

pub fn main() !void {
    var gpa = std.heap.GeneralPurposeAllocator(.{}){};
    defer _ = gpa.deinit();
    const alloc = gpa.allocator();

    const args = try std.process.argsAlloc(alloc);
    defer std.process.argsFree(alloc, args);
    if (args.len < 3) fatal("usage: unsafie-exec <role> <instance>");

    const role = args[1];
    const instance = args[2];

    const lanes_root = env(alloc, "UNSAFIE_LANES", "/var/lib/unsafie/lanes");
    const lane = laneOf(instance);
    const current = try std.fmt.allocPrint(alloc, "{s}/{s}/current", .{ lanes_root, lane });

    var buf: [std.fs.max_path_bytes]u8 = undefined;
    const release = std.fs.readLinkAbsolute(current, &buf) catch |e|
        fatalf(alloc, "cannot read lane symlink {s}: {s}", .{ current, @errorName(e) });

    const python = try std.fmt.allocPrint(alloc, "{s}/venv/bin/python", .{release});
    const cwd = try std.fmt.allocPrint(alloc, "{s}/src/python", .{release});
    const sha = std.fs.path.basename(release);

    var envmap = try std.process.getEnvMap(alloc);
    try envmap.put("UNSAFIE_ROLE", role);
    try envmap.put("UNSAFIE_RELEASE", sha);
    try envmap.put("UNSAFIE_LANE", lane);
    try envmap.put("UNSAFIE_INSTANCE", instance);
    try envmap.put("PYTHONUNBUFFERED", "1");
    if (portOf(instance)) |port| try envmap.put("PORT", port);

    std.posix.chdir(cwd) catch |e|
        fatalf(alloc, "chdir {s}: {s}", .{ cwd, @errorName(e) });

    const argv = [_][]const u8{ python, "-m", "unsafie" };
    const err = std.process.execve(alloc, &argv, &envmap);
    fatalf(alloc, "execve {s}: {s}", .{ python, @errorName(err) });
}

fn laneOf(instance: []const u8) []const u8 {
    if (std.mem.lastIndexOfScalar(u8, instance, '-')) |i| return instance[0..i];
    return instance;
}

fn portOf(instance: []const u8) ?[]const u8 {
    const i = std.mem.lastIndexOfScalar(u8, instance, '-') orelse return null;
    const tail = instance[i + 1 ..];
    _ = std.fmt.parseInt(u16, tail, 10) catch return null;
    return tail;
}

fn env(alloc: std.mem.Allocator, key: []const u8, default: []const u8) []const u8 {
    return std.process.getEnvVarOwned(alloc, key) catch default;
}

fn fatal(msg: []const u8) noreturn {
    std.debug.print("{s}\n", .{msg});
    std.process.exit(1);
}

fn fatalf(alloc: std.mem.Allocator, comptime fmt: []const u8, args: anytype) noreturn {
    const msg = std.fmt.allocPrint(alloc, fmt, args) catch "fatal";
    fatal(msg);
}
