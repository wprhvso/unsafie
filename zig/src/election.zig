const std = @import("std");
const posix = std.posix;

const Heartbeat = struct {
    node: []const u8,
    priority: u8,
    at: i64,
};

pub fn main() !void {
    const alloc = std.heap.page_allocator;
    const node = env(alloc, "NODE_ID", "local");
    const priority: u8 = @intCast(envU16("NODE_PRIORITY", 0));
    const port = envU16("GOSSIP_PORT", 7373);
    const peers_raw = env(alloc, "CLUSTER_PEERS", "");

    var peers = std.ArrayList([]const u8){};
    var it = std.mem.tokenizeScalar(u8, peers_raw, ',');
    while (it.next()) |p| try peers.append(alloc, p);

    const sock = try posix.socket(posix.AF.INET, posix.SOCK.DGRAM, 0);
    defer posix.close(sock);
    const bind_addr = try std.net.Address.parseIp("0.0.0.0", port);
    try posix.bind(sock, &bind_addr.any, bind_addr.getOsSockLen());

    const listener = try std.Thread.spawn(.{}, receive, .{sock});
    listener.detach();

    var buf: [256]u8 = undefined;
    while (true) {
        const msg = try std.fmt.bufPrint(
            &buf,
            "{{\"node\":\"{s}\",\"priority\":{d},\"at\":{d}}}",
            .{ node, priority, std.time.timestamp() },
        );
        for (peers.items) |peer| {
            const dst = std.net.Address.parseIp(peer, port) catch continue;
            _ = posix.sendto(sock, msg, 0, &dst.any, dst.getOsSockLen()) catch {};
        }
        std.Thread.sleep(std.time.ns_per_s);
    }
}

fn receive(sock: posix.socket_t) void {
    var buf: [512]u8 = undefined;
    while (true) {
        const n = posix.recv(sock, &buf, 0) catch continue;
        std.log.info("gossip in: {s}", .{buf[0..n]});
    }
}

fn env(alloc: std.mem.Allocator, key: []const u8, default: []const u8) []const u8 {
    return std.process.getEnvVarOwned(alloc, key) catch default;
}

fn envU16(key: []const u8, default: u16) u16 {
    const v = std.process.getEnvVarOwned(std.heap.page_allocator, key) catch return default;
    return std.fmt.parseInt(u16, v, 10) catch default;
}
