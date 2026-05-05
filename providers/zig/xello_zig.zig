const std = @import("std");

var message: [256]u8 = undefined;

export fn xello_language() [*:0]const u8 {
    return "zig";
}

export fn xello_hello(caller: [*:0]const u8) [*:0]const u8 {
    const safe_caller = if (@intFromPtr(caller) == 0) "unknown" else std.mem.span(caller);
    const text = std.fmt.bufPrintZ(
        &message,
        "hello world from zig implementation, called by {s}",
        .{safe_caller},
    ) catch "hello world from zig implementation, called by unknown";
    return text.ptr;
}
