"""Extract WeChat 4.x SQLCipher keys via frida hook on CCKeyDerivationPBKDF.

Usage:
  python3 extract_key.py --wechat-app ~/Desktop/WeChat.app \
                         --out /tmp/wechat_keys.log \
                         --wait 300
"""
import argparse, os, sys, time
import frida

JS_HOOK = r"""
function buf2hex(buffer) {
    var a = new Uint8Array(buffer); var h = '';
    for (var i = 0; i < a.length; i++) h += ('0' + a[i].toString(16)).slice(-2);
    return h;
}
var found = false;
Process.enumerateModules().forEach(function(m) {
    if (found) return;
    m.enumerateExports().forEach(function(exp) {
        if (found) return;
        if (exp.name === "CCKeyDerivationPBKDF") {
            found = true;
            send("[*] Hook installed on " + m.name);
            Interceptor.attach(exp.address, {
                onEnter: function(args) {
                    this.pwLen = args[2].toInt32();
                    this.saltLen = args[4].toInt32();
                    this.rounds = args[6].toInt32();
                    this.pw = args[1]; this.salt = args[3];
                    this.dk = args[7]; this.dkLen = args[8].toInt32();
                },
                onLeave: function(retval) {
                    if (this.pwLen < 4 || this.pwLen > 256) return;
                    if (this.saltLen < 4 || this.saltLen > 64) return;
                    var saltHex = buf2hex(this.salt.readByteArray(this.saltLen));
                    var dkHex = buf2hex(this.dk.readByteArray(this.dkLen));
                    var pwHex = buf2hex(this.pw.readByteArray(this.pwLen));
                    send("[PBKDF2] r=" + this.rounds + " salt=" + saltHex.slice(0,16) + "...");
                    var f = new File(LOG_PATH_PLACEHOLDER, "a");
                    f.write("rounds=" + this.rounds + "\npw=" + pwHex + "\nsalt=" + saltHex + "\ndk=" + dkHex + "\n\n");
                    f.flush(); f.close();
                }
            });
        }
    });
});
if (!found) send("[!] CCKeyDerivationPBKDF not found");
"""


def on_message(msg, _data):
    if msg.get("type") == "send":
        print(f"[frida] {msg.get('payload')}", flush=True)
    elif msg.get("type") == "error":
        print(f"[frida-error] {msg}", flush=True)


def wait_for_process(device, name: str, timeout: int = 120):
    start = time.time()
    while time.time() - start < timeout:
        for p in device.enumerate_processes():
            if p.name == name:
                return p.pid
        time.sleep(1)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wechat-app", default=os.path.expanduser("~/Desktop/WeChat.app"),
                    help="Path to ad-hoc signed WeChat.app copy (default: ~/Desktop/WeChat.app)")
    ap.add_argument("--out", default="/tmp/wechat_keys.log",
                    help="Output log path for captured keys")
    ap.add_argument("--wait", type=int, default=300,
                    help="Seconds to keep hook active (default 300)")
    ap.add_argument("--mode", choices=["spawn", "attach"], default="attach",
                    help="attach: launch WeChat separately; spawn: frida launches it")
    args = ap.parse_args()

    if os.path.exists(args.out):
        os.remove(args.out)

    js = JS_HOOK.replace("LOG_PATH_PLACEHOLDER", repr(args.out))
    device = frida.get_local_device()

    if args.mode == "spawn":
        bin_path = os.path.join(args.wechat_app, "Contents/MacOS/WeChat")
        print(f"[*] Spawning {bin_path}", flush=True)
        pid = device.spawn([bin_path])
    else:
        print("[*] Attach mode. Launch WeChat now:", flush=True)
        print(f"    open {args.wechat_app}    # or direct: {args.wechat_app}/Contents/MacOS/WeChat", flush=True)
        pid = wait_for_process(device, "WeChat", timeout=120)
        if not pid:
            print("[!] Timed out waiting for WeChat process", flush=True)
            sys.exit(1)

    print(f"[*] Attaching to PID={pid}", flush=True)
    session = device.attach(pid)
    script = session.create_script(js)
    script.on("message", on_message)
    script.load()
    if args.mode == "spawn":
        device.resume(pid)

    print(f"[*] Hook active. In WeChat: log in if needed, then open the conversation you want to export (or 收藏 for favorites). Waiting {args.wait}s...", flush=True)
    start = time.time()
    while time.time() - start < args.wait:
        time.sleep(5)
        if os.path.exists(args.out):
            size = os.path.getsize(args.out)
            print(f"[*] elapsed={int(time.time()-start)}s log={size}B", flush=True)

    try:
        session.detach()
    except Exception:
        pass
    print(f"[*] Done. Keys written to: {args.out}", flush=True)


if __name__ == "__main__":
    main()
