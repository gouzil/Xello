// Bytes are opaque references in Wasm GC and managed pointers in linear Wasm.
function xelloByteApi(api) {
  return {
    make(raw) {
      const bytes = api.xello_bytes_make(raw.length);
      for (let i = 0; i < raw.length; i++)
        api.xello_bytes_set(bytes, i, raw[i]);
      return api.xello_bytes_freeze(bytes);
    },
    read(bytes) {
      const raw = new Uint8Array(api.xello_bytes_length(bytes));
      for (let i = 0; i < raw.length; i++)
        raw[i] = api.xello_bytes_get(bytes, i);
      return raw;
    },
  };
}
