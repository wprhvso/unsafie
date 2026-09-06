const std = @import("std");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});

    const bins = .{
        .{ "unsafie-exec", "src/exec.zig" },
        .{ "unsafie-relay", "src/relay.zig" },
        .{ "unsafie-election", "src/election.zig" },
    };

    inline for (bins) |bin| {
        const exe = b.addExecutable(.{
            .name = bin[0],
            .root_module = b.createModule(.{
                .root_source_file = b.path(bin[1]),
                .target = target,
                .optimize = optimize,
            }),
        });
        b.installArtifact(exe);
    }
}
