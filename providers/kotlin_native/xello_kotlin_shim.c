#include "libxello_kotlin_native_raw_api.h"

const char *xello_language(void) {
    return "kotlin_native";
}

const char *xello_hello(const char *caller) {
    libxello_kotlin_native_raw_ExportedSymbols *symbols = libxello_kotlin_native_raw_symbols();
    return (const char *)symbols->kotlin.root.xelloHello((libxello_kotlin_native_raw_KNativePtr)caller);
}
