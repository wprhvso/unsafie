const std = @import("std");

pub const Ring = struct {
    buf: []u8,
    base: u64 = 0,
    end: u64 = 0,
    pos: usize = 0,
    full: bool = false,
    allocator: std.mem.Allocator,

    pub fn init(allocator: std.mem.Allocator, size: usize) !Ring {
        return .{ .buf = try allocator.alloc(u8, size), .allocator = allocator };
    }

    pub fn deinit(self: *Ring) void {
        self.allocator.free(self.buf);
        self.buf = &.{};
    }

    pub fn append(self: *Ring, data: []const u8) void {
        self.end += data.len;
        if (data.len >= self.buf.len) {
            const tail = data[data.len - self.buf.len ..];
            @memcpy(self.buf, tail);
            self.pos = 0;
            self.full = true;
            self.base = self.end - self.buf.len;
            return;
        }
        var rest = data;
        while (rest.len > 0) {
            const room = self.buf.len - self.pos;
            const n = @min(room, rest.len);
            @memcpy(self.buf[self.pos .. self.pos + n], rest[0..n]);
            self.pos += n;
            if (self.pos == self.buf.len) {
                self.pos = 0;
                self.full = true;
            }
            rest = rest[n..];
        }
        if (self.full) self.base = self.end - self.buf.len;
    }

    pub fn holds(self: *const Ring, off: u64) bool {
        return off >= self.base and off <= self.end;
    }

    pub fn since(self: *const Ring, off: u64, out: []u8) ?usize {
        if (!self.holds(off)) return null;
        const want: usize = @intCast(self.end - off);
        if (want == 0) return 0;
        if (want > out.len) return null;

        if (self.pos >= want) {
            @memcpy(out[0..want], self.buf[self.pos - want .. self.pos]);
            return want;
        }
        const head = want - self.pos;
        @memcpy(out[0..head], self.buf[self.buf.len - head ..]);
        @memcpy(out[head..want], self.buf[0..self.pos]);
        return want;
    }

    pub fn pending(self: *const Ring, off: u64) u64 {
        if (off > self.end) return 0;
        return self.end - off;
    }
};

pub const Buffer = struct {
    data: []u8 = &.{},
    len: usize = 0,
    start: usize = 0,
    allocator: std.mem.Allocator,

    pub fn init(allocator: std.mem.Allocator) Buffer {
        return .{ .allocator = allocator };
    }

    pub fn deinit(self: *Buffer) void {
        if (self.data.len > 0) self.allocator.free(self.data);
        self.data = &.{};
        self.len = 0;
        self.start = 0;
    }

    pub fn readable(self: *const Buffer) []const u8 {
        return self.data[self.start..self.len];
    }

    pub fn size(self: *const Buffer) usize {
        return self.len - self.start;
    }

    pub fn consume(self: *Buffer, n: usize) void {
        self.start += n;
        if (self.start == self.len) {
            self.start = 0;
            self.len = 0;
        }
    }

    pub fn compact(self: *Buffer) void {
        if (self.start == 0) return;
        const live = self.len - self.start;
        std.mem.copyForwards(u8, self.data[0..live], self.data[self.start..self.len]);
        self.start = 0;
        self.len = live;
    }

    pub fn ensure(self: *Buffer, extra: usize) !void {
        if (self.data.len - self.len >= extra) return;
        self.compact();
        if (self.data.len - self.len >= extra) return;
        const want = std.math.ceilPowerOfTwo(usize, @max(self.len + extra, 4096)) catch return error.OutOfMemory;
        self.data = try self.allocator.realloc(self.data, want);
    }

    pub fn append(self: *Buffer, bytes: []const u8) !void {
        try self.ensure(bytes.len);
        @memcpy(self.data[self.len .. self.len + bytes.len], bytes);
        self.len += bytes.len;
    }

    pub fn tail(self: *Buffer, n: usize) ![]u8 {
        try self.ensure(n);
        const out = self.data[self.len .. self.len + n];
        self.len += n;
        return out;
    }
};
