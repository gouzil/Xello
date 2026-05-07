const std = @import("std");

const languages = [_][]const u8{ "python", "c", "go", "rust", "cpp", "zig", "kotlin_native", "wasm" };
const HelloFn = *const fn ([*c]const u8) callconv(.c) [*c]const u8;

const CallResult = struct {
    caller: []const u8,
    callee: []const u8,
    bridge: []const u8,
    duration_ns: u64,
    message: []const u8,
};

fn nowNs() u64 {
    return @intCast(std.time.nanoTimestamp());
}

fn elapsedNsSince(start_ns: u64) u64 {
    const end_ns = nowNs();
    return if (end_ns <= start_ns) 1 else end_ns - start_ns;
}

fn isLanguage(language: []const u8) bool {
    for (languages) |candidate| {
        if (std.mem.eql(u8, language, candidate)) return true;
    }
    return false;
}

fn sharedExt() []const u8 {
    return switch (@import("builtin").target.os.tag) {
        .macos => ".dylib",
        .windows => ".dll",
        else => ".so",
    };
}

fn bridgeKind(callee: []const u8) ?[]const u8 {
    if (std.mem.eql(u8, callee, "python")) return "Python shared library via Python/C API";
    if (std.mem.eql(u8, callee, "c")) return "C shared library via C ABI";
    if (std.mem.eql(u8, callee, "go")) return "Go shared library via C ABI";
    if (std.mem.eql(u8, callee, "rust")) return "Rust shared library via C ABI";
    if (std.mem.eql(u8, callee, "cpp")) return "C++ shared library via C ABI";
    if (std.mem.eql(u8, callee, "zig")) return "direct Zig function";
    if (std.mem.eql(u8, callee, "kotlin_native")) return "Kotlin/Native dynamic library via C ABI";
    if (std.mem.eql(u8, callee, "wasm")) return "WebAssembly C ABI shim";
    return null;
}

fn zigHello(allocator: std.mem.Allocator, caller: []const u8) ![]const u8 {
    return std.fmt.allocPrint(allocator, "hello world from zig implementation, called by {s}", .{caller});
}

fn callProvider(allocator: std.mem.Allocator, callee: []const u8) !struct { message: []const u8, duration_ns: u64 } {
    const path = try std.fmt.allocPrint(allocator, "build/lib/libxello_{s}{s}", .{ callee, sharedExt() });
    defer allocator.free(path);

    var library = try std.DynLib.open(path);
    defer library.close();
    const hello = library.lookup(HelloFn, "xello_hello") orelse return error.MissingProviderSymbol;

    const start = nowNs();
    const message_ptr = hello("zig");
    const message = try allocator.dupe(u8, std.mem.span(message_ptr));
    const duration_ns = elapsedNsSince(start);
    return .{
        .message = message,
        .duration_ns = duration_ns,
    };
}

fn callEdge(allocator: std.mem.Allocator, callee: []const u8) !CallResult {
    if (!isLanguage(callee)) return error.UnknownLanguage;
    const bridge = bridgeKind(callee) orelse return error.UnknownLanguage;

    if (std.mem.eql(u8, callee, "zig")) {
        const start = nowNs();
        const message = try zigHello(allocator, "zig");
        return .{ .caller = "zig", .callee = callee, .bridge = bridge, .duration_ns = elapsedNsSince(start), .message = message };
    }
    const item = try callProvider(allocator, callee);
    return .{ .caller = "zig", .callee = callee, .bridge = bridge, .duration_ns = item.duration_ns, .message = item.message };
}

fn printJsonString(stdout: *std.Io.Writer, value: []const u8) !void {
    try stdout.print("\"", .{});
    for (value) |ch| {
        switch (ch) {
            '"' => try stdout.print("\\\"", .{}),
            '\\' => try stdout.print("\\\\", .{}),
            '\n' => try stdout.print("\\n", .{}),
            '\r' => try stdout.print("\\r", .{}),
            '\t' => try stdout.print("\\t", .{}),
            else => try stdout.print("{c}", .{ch}),
        }
    }
    try stdout.print("\"", .{});
}

fn printResults(results: []const CallResult, json_output: bool) !void {
    var stdout_buffer: [8192]u8 = undefined;
    var stdout_writer = std.fs.File.stdout().writer(&stdout_buffer);
    const stdout: *std.Io.Writer = &stdout_writer.interface;
    defer stdout.flush() catch {};

    if (json_output) {
        try stdout.print("[\n", .{});
        for (results, 0..) |item, index| {
            const comma = if (index + 1 == results.len) "" else ",";
            try stdout.print("  {{\"caller\":", .{});
            try printJsonString(stdout, item.caller);
            try stdout.print(",\"callee\":", .{});
            try printJsonString(stdout, item.callee);
            try stdout.print(",\"bridge\":", .{});
            try printJsonString(stdout, item.bridge);
            try stdout.print(",\"duration_ns\":{},\"message\":", .{item.duration_ns});
            try printJsonString(stdout, item.message);
            try stdout.print(",\"output\":", .{});
            try stdout.print("\"zig runner -> {s} implementation via {s}: {s}\"", .{ item.callee, item.bridge, item.message });
            try stdout.print("}}{s}\n", .{comma});
        }
        try stdout.print("]\n", .{});
        return;
    }

    for (results) |item| {
        try stdout.print("zig runner -> {s} implementation via {s}: {s} (duration_ns={})\n", .{ item.callee, item.bridge, item.message, item.duration_ns });
    }
}

fn delegateToPython(allocator: std.mem.Allocator, json_output: bool, args: []const []const u8) !void {
    var command_buffer: [16][]const u8 = undefined;
    var command_len: usize = 0;
    command_buffer[command_len] = "python3";
    command_len += 1;
    command_buffer[command_len] = "tools/xello.py";
    command_len += 1;
    if (json_output) {
        command_buffer[command_len] = "--json";
        command_len += 1;
    }
    for (args) |arg| {
        if (command_len >= command_buffer.len) return error.TooManyArguments;
        command_buffer[command_len] = arg;
        command_len += 1;
    }

    var child = std.process.Child.init(command_buffer[0..command_len], allocator);
    child.stdout_behavior = .Inherit;
    child.stderr_behavior = .Inherit;
    const term = try child.spawnAndWait();
    if (term != .Exited or term.Exited != 0) return error.PythonRunnerFailed;
}

pub fn main() !void {
    var gpa = std.heap.GeneralPurposeAllocator(.{}){};
    defer _ = gpa.deinit();
    const allocator = gpa.allocator();
    const raw_args = try std.process.argsAlloc(allocator);
    defer std.process.argsFree(allocator, raw_args);

    var index: usize = 1;
    var json_output = false;
    if (raw_args.len > 1 and std.mem.eql(u8, raw_args[1], "--json")) {
        json_output = true;
        index = 2;
    }
    if (index >= raw_args.len) return error.InvalidArguments;

    const command = raw_args[index];
    if (std.mem.eql(u8, command, "call")) {
        if (index + 1 >= raw_args.len) return error.InvalidArguments;
        var result = try callEdge(allocator, raw_args[index + 1]);
        defer allocator.free(result.message);
        try printResults((&result)[0..1], json_output);
        return;
    }

    try delegateToPython(allocator, json_output, raw_args[index..]);
}
