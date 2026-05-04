package main

/*
#include <stdlib.h>
*/
import "C"
import "unsafe"

var lastMessage *C.char

//export xello_language
func xello_language() *C.char {
	return C.CString("go")
}

//export xello_hello
func xello_hello(caller *C.char) *C.char {
	if lastMessage != nil {
		C.free(unsafe.Pointer(lastMessage))
	}
	name := "unknown"
	if caller != nil {
		name = C.GoString(caller)
	}
	lastMessage = C.CString("hello world from go implementation, called by " + name)
	return lastMessage
}

func main() {}
