const std = @import("std");
const posix = std.posix;

const edgemod = @import("edge.zig");
const log = @import("log.zig");

const usage =
    \\unsafie-edge — the HTTP/1.1 exit of the unsafie tunnel
    \\
    \\  --listen host:port      where nginx proxies to        (default 127.0.0.1:8091)
    \\  --resolver host:port    what resolves exit targets    (default 1.1.1.1:53)
    \\  --region name           advertised in the hello       (default $UNSAFIE_REGION)
    \\  --country code          advertised in the hello       (default $UNSAFIE_COUNTRY)
    \\  --asn number            advertised in the hello
    \\  --streams n             per session stream ceiling    (default 4096)
    \\  --sessions n            live session ceiling          (default 8192)
    \\  --replay bytes          resume window per session     (default 4194304)
    \\  --slot letter           first character of every id this process mints,
    \\                          so nginx can route both legs of a session to it
    \\  --verbose               log every session transition
    \\
;

fn envOr(name: []const u8, fallback: []const u8) []const u8 {
    return posix.getenv(name) orelse fallback;
}

fn parseAddress(text: []const u8, default_port: u16) !std.net.Address {
    if (std.mem.lastIndexOfScalar(u8, text, ':')) |i| {
        const host = text[0..i];
        const port = try std.fmt.parseInt(u16, text[i + 1 ..], 10);
        return std.net.Address.parseIp(host, port);
    }
    return std.net.Address.parseIp(text, default_port);
}

pub fn main() !void {
    var debug_allocator: std.heap.DebugAllocator(.{}) = .init;
    defer _ = debug_allocator.deinit();
    const allocator = debug_allocator.allocator();

    var cfg = edgemod.Config{
        .listen = try parseAddress(envOr("UNSAFIE_LISTEN", "127.0.0.1:8091"), 8091),
        .resolver = try parseAddress(envOr("UNSAFIE_RESOLVER", "1.1.1.1:53"), 53),
        .region = envOr("UNSAFIE_REGION", ""),
        .country = envOr("UNSAFIE_COUNTRY", ""),
    };
    if (posix.getenv("UNSAFIE_ASN")) |text| {
        cfg.asn = std.fmt.parseInt(u32, text, 10) catch 0;
    }

    var args = try std.process.argsWithAllocator(allocator);
    defer args.deinit();
    _ = args.next();

    while (args.next()) |arg| {
        if (std.mem.eql(u8, arg, "--help") or std.mem.eql(u8, arg, "-h")) {
            std.debug.print("{s}", .{usage});
            return;
        } else if (std.mem.eql(u8, arg, "--verbose")) {
            log.verbose = true;
        } else if (std.mem.eql(u8, arg, "--listen")) {
            cfg.listen = try parseAddress(args.next() orelse return error.MissingValue, 8091);
        } else if (std.mem.eql(u8, arg, "--resolver")) {
            cfg.resolver = try parseAddress(args.next() orelse return error.MissingValue, 53);
        } else if (std.mem.eql(u8, arg, "--region")) {
            cfg.region = args.next() orelse return error.MissingValue;
        } else if (std.mem.eql(u8, arg, "--country")) {
            cfg.country = args.next() orelse return error.MissingValue;
        } else if (std.mem.eql(u8, arg, "--asn")) {
            cfg.asn = try std.fmt.parseInt(u32, args.next() orelse return error.MissingValue, 10);
        } else if (std.mem.eql(u8, arg, "--streams")) {
            cfg.max_streams = try std.fmt.parseInt(u32, args.next() orelse return error.MissingValue, 10);
        } else if (std.mem.eql(u8, arg, "--sessions")) {
            cfg.max_sessions = try std.fmt.parseInt(u32, args.next() orelse return error.MissingValue, 10);
        } else if (std.mem.eql(u8, arg, "--slot")) {
            const text = args.next() orelse return error.MissingValue;
            if (text.len != 1) return error.BadUsage;
            cfg.slot = text[0];
        } else if (std.mem.eql(u8, arg, "--replay")) {
            cfg.replay_bytes = try std.fmt.parseInt(usize, args.next() orelse return error.MissingValue, 10);
        } else {
            std.debug.print("unknown option: {s}\n{s}", .{ arg, usage });
            return error.BadUsage;
        }
    }

    const sa = posix.Sigaction{
        .handler = .{ .handler = posix.SIG.IGN },
        .mask = posix.sigemptyset(),
        .flags = 0,
    };
    posix.sigaction(posix.SIG.PIPE, &sa, null);

    const edge = try edgemod.Edge.init(allocator, cfg);
    defer edge.deinit();

    log.info("listening on {f}, resolver {f}, region {s}/{s}, replay {d} KiB", .{
        cfg.listen,
        cfg.resolver,
        if (cfg.region.len == 0) "-" else cfg.region,
        if (cfg.country.len == 0) "-" else cfg.country,
        cfg.replay_bytes / 1024,
    });

    try edge.run();
}

test {
    _ = @import("usp.zig");
    _ = @import("http.zig");
    _ = @import("ring.zig");
    _ = @import("session.zig");
    _ = @import("dns.zig");
    _ = @import("edge.zig");
}
