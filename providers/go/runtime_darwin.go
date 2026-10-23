package main

/*
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>

// Go runtime threads can outlive a caller's dlclose.
__attribute__((constructor)) static void keep_go_runtime_loaded(void) {
    Dl_info image;
    if (!dladdr((const void *)keep_go_runtime_loaded, &image) ||
        !dlopen(image.dli_fname, RTLD_NOW | RTLD_NODELETE)) {
        fprintf(stderr, "cannot keep the Go provider runtime loaded\n");
        abort();
    }
}
*/
import "C"
