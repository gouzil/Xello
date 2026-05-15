const std = @import("std");

const languages = [_][]const u8{ "python", "c", "go", "rust", "cpp", "zig", "kotlin_native", "wasm" };
const HelloFn = *const fn ([*c]const u8) callconv(.c) [*c]const u8;

const CallResult = struct {
    step: usize = 0,
    caller: []const u8,
    callee: []const u8,
    bridge: []const u8,
    duration_ns: u64,
    message: []const u8,
};

const ProviderCall = struct {
    message: []const u8,
    duration_ns: u64,
};

fn nowNs(io: std.Io) u64 {
    return @intCast(std.Io.Timestamp.now(io, .awake).nanoseconds);
}

fn elapsedNsSince(io: std.Io, start_ns: u64) u64 {
    const end_ns = nowNs(io);
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

fn providerBridgeKind(callee: []const u8) ?[]const u8 {
    if (std.mem.eql(u8, callee, "python")) return "Python provider function via Python/C API";
    if (std.mem.eql(u8, callee, "c")) return "C provider function via C ABI";
    if (std.mem.eql(u8, callee, "go")) return "Go provider function via C ABI";
    if (std.mem.eql(u8, callee, "rust")) return "Rust provider function via C ABI";
    if (std.mem.eql(u8, callee, "cpp")) return "C++ provider function via C ABI";
    if (std.mem.eql(u8, callee, "zig")) return "Zig provider function via C ABI";
    if (std.mem.eql(u8, callee, "kotlin_native")) return "Kotlin/Native provider function via C ABI";
    if (std.mem.eql(u8, callee, "wasm")) return "WebAssembly C ABI shim";
    return null;
}

fn zigHello(allocator: std.mem.Allocator, caller: []const u8) ![]const u8 {
    return std.fmt.allocPrint(allocator, "hello world from zig implementation, called by {s}", .{caller});
}

fn callProvider(io: std.Io, allocator: std.mem.Allocator, callee: []const u8) !ProviderCall {
    return callProviderAs(io, allocator, "zig", callee);
}

fn callProviderAs(io: std.Io, allocator: std.mem.Allocator, caller: []const u8, callee: []const u8) !ProviderCall {
    const path = try std.fmt.allocPrint(allocator, "build/lib/libxello_{s}{s}", .{ callee, sharedExt() });
    defer allocator.free(path);

    var library = try std.DynLib.open(path);
    defer library.close();
    const hello = library.lookup(HelloFn, "xello_hello") orelse return error.MissingProviderSymbol;

    const start = nowNs(io);
    const caller_z = try allocator.dupeZ(u8, caller);
    defer allocator.free(caller_z);
    const message_ptr = hello(caller_z.ptr);
    const message = try allocator.dupe(u8, std.mem.span(message_ptr));
    const duration_ns = elapsedNsSince(io, start);
    return .{
        .message = message,
        .duration_ns = duration_ns,
    };
}

fn callEdge(io: std.Io, allocator: std.mem.Allocator, callee: []const u8) !CallResult {
    if (!isLanguage(callee)) return error.UnknownLanguage;
    const bridge = bridgeKind(callee) orelse return error.UnknownLanguage;

    if (std.mem.eql(u8, callee, "zig")) {
        const start = nowNs(io);
        const message = try zigHello(allocator, "zig");
        return .{ .caller = "zig", .callee = callee, .bridge = bridge, .duration_ns = elapsedNsSince(io, start), .message = message };
    }
    const item = try callProvider(io, allocator, callee);
    return .{ .caller = "zig", .callee = callee, .bridge = bridge, .duration_ns = item.duration_ns, .message = item.message };
}

fn callEdgeAs(io: std.Io, allocator: std.mem.Allocator, caller: []const u8, callee: []const u8) !CallResult {
    if (std.mem.eql(u8, caller, "zig")) return callEdge(io, allocator, callee);
    if (!isLanguage(caller) or !isLanguage(callee)) return error.UnknownLanguage;
    const bridge = providerBridgeKind(callee) orelse return error.UnknownLanguage;
    if (std.mem.eql(u8, caller, "wasm") and std.mem.eql(u8, callee, "wasm")) {
        const start = nowNs(io);
        const message = try allocator.dupe(u8, "hello world from wasm implementation, called by wasm");
        return .{ .caller = caller, .callee = callee, .bridge = "WebAssembly runtime host", .duration_ns = elapsedNsSince(io, start), .message = message };
    }
    const item = try callProviderAs(io, allocator, caller, callee);
    return .{ .caller = caller, .callee = callee, .bridge = bridge, .duration_ns = item.duration_ns, .message = item.message };
}

fn writeStdout(io: std.Io, value: []const u8) !void {
    try std.Io.File.stdout().writeStreamingAll(io, value);
}

fn printJsonString(io: std.Io, value: []const u8) !void {
    try writeStdout(io, "\"");
    for (value) |ch| {
        switch (ch) {
            '"' => try writeStdout(io, "\\\""),
            '\\' => try writeStdout(io, "\\\\"),
            '\n' => try writeStdout(io, "\\n"),
            '\r' => try writeStdout(io, "\\r"),
            '\t' => try writeStdout(io, "\\t"),
            else => try writeStdout(io, (&ch)[0..1]),
        }
    }
    try writeStdout(io, "\"");
}

fn printResults(io: std.Io, results: []const CallResult, json_output: bool) !void {
    var buffer: [4096]u8 = undefined;
    if (json_output) {
        try writeStdout(io, "[\n");
        for (results, 0..) |item, index| {
            const comma = if (index + 1 == results.len) "" else ",";
            try writeStdout(io, "  {");
            if (item.step > 0) {
                const step_prefix = try std.fmt.bufPrint(&buffer, "\"step\":{},", .{item.step});
                try writeStdout(io, step_prefix);
            }
            try writeStdout(io, "\"caller\":");
            try printJsonString(io, item.caller);
            try writeStdout(io, ",\"callee\":");
            try printJsonString(io, item.callee);
            try writeStdout(io, ",\"bridge\":");
            try printJsonString(io, item.bridge);
            const prefix = try std.fmt.bufPrint(&buffer, ",\"duration_ns\":{},\"message\":", .{item.duration_ns});
            try writeStdout(io, prefix);
            try printJsonString(io, item.message);
            try writeStdout(io, ",\"output\":");
            const output = try std.fmt.bufPrint(&buffer, "zig runner -> {s} implementation via {s}: {s}", .{ item.callee, item.bridge, item.message });
            try printJsonString(io, output);
            const suffix = try std.fmt.bufPrint(&buffer, "}}{s}\n", .{comma});
            try writeStdout(io, suffix);
        }
        try writeStdout(io, "]\n");
        return;
    }

    for (results) |item| {
        const step_prefix = if (item.step > 0) try std.fmt.bufPrint(&buffer, "step={} ", .{item.step}) else "";
        try writeStdout(io, step_prefix);
        const line = try std.fmt.bufPrint(&buffer, "{s} runner -> {s} implementation via {s}: {s} (duration_ns={})\n", .{ item.caller, item.callee, item.bridge, item.message, item.duration_ns });
        try writeStdout(io, line);
    }
}

fn loadLanguages(io: std.Io, allocator: std.mem.Allocator) ![][]const u8 {
    const manifest = std.Io.Dir.cwd().readFileAlloc(io, "build/xello_languages.json", allocator, .limited(8192)) catch {
        const fallback = try allocator.alloc([]const u8, 5);
        fallback[0] = "python";
        fallback[1] = "c";
        fallback[2] = "go";
        fallback[3] = "rust";
        fallback[4] = "cpp";
        return fallback;
    };
    defer allocator.free(manifest);
    var selected = try std.ArrayList([]const u8).initCapacity(allocator, languages.len);
    defer selected.deinit(allocator);
    for (languages) |language| {
        const token = try std.fmt.allocPrint(allocator, "\"{s}\"", .{language});
        defer allocator.free(token);
        if (std.mem.indexOf(u8, manifest, token) != null) {
            try selected.append(allocator, language);
        }
    }
    return selected.toOwnedSlice(allocator);
}

fn parseEdges(allocator: std.mem.Allocator, raw: []const u8) ![][2][]const u8 {
    var edges = try std.ArrayList([2][]const u8).initCapacity(allocator, languages.len);
    defer edges.deinit(allocator);
    var iterator = std.mem.splitScalar(u8, raw, ',');
    while (iterator.next()) |item| {
        const edge = std.mem.trim(u8, item, " \t\r\n");
        if (edge.len == 0) continue;
        const separator = std.mem.indexOfScalar(u8, edge, ':') orelse return error.InvalidArguments;
        const caller = std.mem.trim(u8, edge[0..separator], " \t\r\n");
        const callee = std.mem.trim(u8, edge[separator + 1 ..], " \t\r\n");
        if (!isLanguage(caller) or !isLanguage(callee)) return error.UnknownLanguage;
        try edges.append(allocator, .{ caller, callee });
    }
    if (edges.items.len == 0) return error.InvalidArguments;
    return edges.toOwnedSlice(allocator);
}

fn runMatrix(io: std.Io, allocator: std.mem.Allocator, json_output: bool) !void {
    const current_languages = try loadLanguages(io, allocator);
    defer allocator.free(current_languages);
    var results = try std.ArrayList(CallResult).initCapacity(allocator, current_languages.len * current_languages.len);
    defer {
        for (results.items) |item| allocator.free(item.message);
        results.deinit(allocator);
    }
    for (current_languages) |caller| {
        for (current_languages) |callee| {
            try results.append(allocator, try callEdgeAs(io, allocator, caller, callee));
        }
    }
    try printResults(io, results.items, json_output);
}

fn runFanout(io: std.Io, allocator: std.mem.Allocator, caller: []const u8, json_output: bool) !void {
    if (!isLanguage(caller)) return error.UnknownLanguage;
    const current_languages = try loadLanguages(io, allocator);
    defer allocator.free(current_languages);
    var results = try std.ArrayList(CallResult).initCapacity(allocator, current_languages.len);
    defer {
        for (results.items) |item| allocator.free(item.message);
        results.deinit(allocator);
    }
    for (current_languages) |callee| {
        try results.append(allocator, try callEdgeAs(io, allocator, caller, callee));
    }
    try printResults(io, results.items, json_output);
}

fn runChain(io: std.Io, allocator: std.mem.Allocator, raw_edges: []const u8, json_output: bool) !void {
    const edges = try parseEdges(allocator, raw_edges);
    defer allocator.free(edges);
    var results = try std.ArrayList(CallResult).initCapacity(allocator, edges.len);
    defer {
        for (results.items) |item| allocator.free(item.message);
        results.deinit(allocator);
    }
    for (edges, 0..) |edge, index| {
        var result = try callEdgeAs(io, allocator, edge[0], edge[1]);
        result.step = index + 1;
        try results.append(allocator, result);
    }
    try printResults(io, results.items, json_output);
}

pub fn main(init: std.process.Init) !void {
    const allocator = init.gpa;
    const io = init.io;
    const raw_args = try init.minimal.args.toSlice(init.arena.allocator());

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
        var result = try callEdge(io, allocator, raw_args[index + 1]);
        defer allocator.free(result.message);
        try printResults(io, (&result)[0..1], json_output);
        return;
    }

    if (std.mem.eql(u8, command, "matrix")) {
        try runMatrix(io, allocator, json_output);
        return;
    }
    if (std.mem.eql(u8, command, "fanout")) {
        if (index + 1 >= raw_args.len) return error.InvalidArguments;
        try runFanout(io, allocator, raw_args[index + 1], json_output);
        return;
    }
    if (std.mem.eql(u8, command, "chain")) {
        if (index + 2 >= raw_args.len or !std.mem.eql(u8, raw_args[index + 1], "--edges")) return error.InvalidArguments;
        try runChain(io, allocator, raw_args[index + 2], json_output);
        return;
    }
    return error.InvalidArguments;
}
