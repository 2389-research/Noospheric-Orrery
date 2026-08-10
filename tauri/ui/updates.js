// ABOUTME: Thin host for the manual update window — runs the shared update
// ABOUTME: flow in "manual" mode so it announces "up to date" and errors.
window.OrreryUpdate.mountUpdateFlow({
  container: document.getElementById("update-root"),
  mode: "manual",
  onDone: () => {},
});
