#include "xello.h"

#include <stdio.h>

const char *xello_language(void) {
    return "c";
}

const char *xello_hello(const char *caller) {
    static char buffer[256];
    const char *safe_caller = caller == NULL ? "unknown" : caller;
    snprintf(buffer, sizeof(buffer), "hello world from c implementation, called by %s", safe_caller);
    return buffer;
}
