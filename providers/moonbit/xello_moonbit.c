#include "xello.h"

#include <moonbit.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

extern moonbit_bytes_t xello_moonbit_hello(moonbit_bytes_t caller);

static moonbit_bytes_t message = NULL;

__attribute__((constructor)) static void initialize(void) {
    moonbit_init();
}

__attribute__((destructor)) static void cleanup(void) {
    if (message != NULL) {
        moonbit_decref(message);
    }
}

__attribute__((visibility("default"))) const char *xello_language(void) {
    return "moonbit";
}

__attribute__((visibility("default"))) const char *xello_hello(const char *caller) {
    const char *safe_caller = caller == NULL ? "unknown" : caller;
    size_t caller_length = strlen(safe_caller);
    if (caller_length > INT32_MAX) {
        fprintf(stderr, "MoonBit caller exceeds the runtime byte limit\n");
        abort();
    }
    moonbit_bytes_t input = moonbit_make_bytes_raw((int32_t)caller_length);
    memcpy(input, safe_caller, caller_length);
    if (message != NULL) {
        moonbit_decref(message);
    }
    message = xello_moonbit_hello(input);
    return (const char *)message;
}
