#include <stdio.h>

const char *xello_language(void) {
    return "wasm";
}

const char *xello_hello(const char *caller) {
    static char message[256];
    const char *safe_caller = caller == 0 ? "unknown" : caller;
    snprintf(message, sizeof(message), "hello world from wasm implementation, called by %s", safe_caller);
    return message;
}
