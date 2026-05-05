#include "xello.h"

#include <cstdio>
#include <string>

extern "C" const char *xello_language(void) {
    return "cpp";
}

extern "C" const char *xello_hello(const char *caller) {
    static std::string message;
    const char *safe_caller = caller == nullptr ? "unknown" : caller;
    message = "hello world from cpp implementation, called by ";
    message += safe_caller;
    return message.c_str();
}
