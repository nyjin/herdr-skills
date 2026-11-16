// winlist [owner]: on-screen windows as JSON lines {id, owner, name, x, y, w, h}
import CoreGraphics
import Foundation
let owner = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : nil
let list = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as! [[String: Any]]
for w in list {
    let o = w[kCGWindowOwnerName as String] as? String ?? ""
    if let owner = owner, o != owner { continue }
    let b = w[kCGWindowBounds as String] as? [String: Double] ?? [:]
    let d: [String: Any] = ["id": w[kCGWindowNumber as String] as? Int ?? 0, "owner": o, "pid": w[kCGWindowOwnerPID as String] as? Int ?? 0,
                            "name": w[kCGWindowName as String] as? String ?? "", "layer": w[kCGWindowLayer as String] as? Int ?? 0,
                            "x": b["X"] ?? 0, "y": b["Y"] ?? 0, "w": b["Width"] ?? 0, "h": b["Height"] ?? 0]
    print(String(data: try! JSONSerialization.data(withJSONObject: d, options: [.sortedKeys]), encoding: .utf8)!)
}
