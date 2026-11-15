// latency2 <window-id> <trials> <gap-ms> -- <trigger command...>
// Key-to-photon for one window (also when other windows cover it): grabs the window, runs the trigger, then grabs as
// fast as it can until the window's pixels change. Prints one JSON line per trial {ms, grabs, grab_ms}.
import CoreGraphics
import Foundation

let a = CommandLine.arguments
let wid = CGWindowID(UInt32(a[1])!)
let trials = Int(a[2])!, gap = Double(a[3])! / 1000
let trigger = Array(a[(a.firstIndex(of: "--")! + 1)...])

func grab() -> [UInt8] {
    guard let img = CGWindowListCreateImage(.null, .optionIncludingWindow, wid, [.boundsIgnoreFraming, .nominalResolution]),
          let data = img.dataProvider?.data, let p = CFDataGetBytePtr(data) else { return [] }
    let n = CFDataGetLength(data)
    var sample = [UInt8](); sample.reserveCapacity(8192)
    var i = n / 8   // skip the title bar and tab row
    while i < n { sample.append(p[i]); i += max(1, n / 8192) }
    return sample
}
func now() -> Double { Date().timeIntervalSince1970 * 1000 }

for _ in 0..<trials {
    var base = grab()
    Thread.sleep(forTimeInterval: 0.05)
    let again = grab()
    if again != base { base = again }
    let p = Process()
    p.executableURL = URL(fileURLWithPath: "/usr/bin/env")
    p.arguments = trigger
    p.standardOutput = FileHandle.nullDevice; p.standardError = FileHandle.nullDevice
    let t0 = now()
    try! p.run()
    var grabs = 0, grabMs = 0.0, changed = -1.0
    while now() - t0 < 3000 {
        let g0 = now(); let g = grab(); grabs += 1; grabMs += now() - g0
        if g != base { changed = now() - t0; break }
    }
    p.waitUntilExit()
    let d: [String: Any] = ["t0": (t0 * 10).rounded() / 10, "ms": (changed * 10).rounded() / 10, "grabs": grabs, "grab_ms": (grabMs / Double(max(grabs, 1)) * 10).rounded() / 10]
    print(String(data: try! JSONSerialization.data(withJSONObject: d, options: [.sortedKeys]), encoding: .utf8)!)
    fflush(stdout)
    Thread.sleep(forTimeInterval: gap)
}
