#include <dlfcn.h>
#include <node_api.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

typedef const char *(*xello_hello_fn)(const char *);

static napi_value call_provider(napi_env env, napi_callback_info info) {
    size_t argc = 2;
    napi_value argv[2];
    if (napi_get_cb_info(env, info, &argc, argv, NULL, NULL) != napi_ok || argc != 2) {
        napi_throw_type_error(env, NULL, "expected caller and callee strings");
        return NULL;
    }
    char names[2][64];
    for (size_t i = 0; i < 2; i++) {
        size_t length;
        if (napi_get_value_string_utf8(env, argv[i], NULL, 0, &length) != napi_ok || length == 0 ||
            length >= sizeof(names[i]) ||
            napi_get_value_string_utf8(env, argv[i], names[i], sizeof(names[i]), &length) != napi_ok) {
            napi_throw_type_error(env, NULL, "invalid language name");
            return NULL;
        }
        for (size_t j = 0; j < length; j++) {
            if (!((names[i][j] >= 'a' && names[i][j] <= 'z') || names[i][j] == '_')) {
                napi_throw_type_error(env, NULL, "invalid language name");
                return NULL;
            }
        }
    }
#ifdef __APPLE__
    const char *ext = ".dylib";
#else
    const char *ext = ".so";
#endif
    char path[128];
    snprintf(path, sizeof(path), "build/lib/libxello_%s%s", names[1], ext);
    void *handle = dlopen(path, RTLD_NOW | RTLD_LOCAL);
    if (handle == NULL) {
        napi_throw_error(env, NULL, dlerror());
        return NULL;
    }
    xello_hello_fn hello = (xello_hello_fn)dlsym(handle, "xello_hello");
    if (hello == NULL) {
        dlclose(handle);
        napi_throw_error(env, NULL, "provider is missing xello_hello");
        return NULL;
    }
    struct timespec start, end;
    clock_gettime(CLOCK_MONOTONIC, &start);
    const char *raw = hello(names[0]);
    clock_gettime(CLOCK_MONOTONIC, &end);
    napi_value result, message, duration;
    int64_t elapsed = (int64_t)(end.tv_sec - start.tv_sec) * 1000000000LL + end.tv_nsec - start.tv_nsec;
    napi_status status =
        raw == NULL ? napi_generic_failure : napi_create_buffer_copy(env, strlen(raw), raw, NULL, &message);
    dlclose(handle);
    if (status != napi_ok || napi_create_bigint_int64(env, elapsed, &duration) != napi_ok ||
        napi_create_array_with_length(env, 2, &result) != napi_ok ||
        napi_set_element(env, result, 0, message) != napi_ok || napi_set_element(env, result, 1, duration) != napi_ok) {
        napi_throw_error(env, NULL, "cannot copy provider result");
        return NULL;
    }
    return result;
}

static napi_value initialize(napi_env env, napi_value exports) {
    napi_value function;
    if (napi_create_function(env, "call", NAPI_AUTO_LENGTH, call_provider, NULL, &function) != napi_ok ||
        napi_set_named_property(env, exports, "call", function) != napi_ok) {
        napi_throw_error(env, NULL, "cannot initialize C ABI bridge");
        return NULL;
    }
    return exports;
}

NAPI_MODULE(xello_moonbit_node, initialize)
