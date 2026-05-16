#include <pybind11/pybind11.h>

#include <string>

namespace py = pybind11;

static std::string hello_from_cpp(const std::string &caller) {
    return "hello world from cpp implementation, called by " + caller;
}

PYBIND11_MODULE(xello_cpp_pybind, module) {
    module.def("language", []() { return "cpp"; });
    module.def("hello", [](const std::string &caller) { return hello_from_cpp(caller); });
}
