const $ = id => document.getElementById(id);
let state = {};
let busy = false;
function render() {
  const consent = Boolean(state.authorized && state.lease?.persistent);
  const pending = Boolean(state.pendingPair?.id);
  const profile = state.localProfile?.email || state.profileBinding?.userName ||
    state.boundProfile?.userName || "Profil Chrome";
  $("profile").textContent = profile;
  $("status").textContent = consent ? "Terhubung - Izin berkelanjutan aktif" :
    pending ? "Permintaan Zagent tersedia - siap disetujui" :
    state.connected ? "Terhubung - menunggu persetujuan" :
    "Menunggu permintaan akses dari Zagent";
  $("approve").disabled = busy || consent ||
    !(pending || (state.connected && !state.profileMismatch));
  $("disconnect").disabled = busy || !state.connected || Boolean(state.profileMismatch);
  $("error").textContent = [state.error, state.warning].filter(Boolean).join(" ");
}
async function act(action) {
  if (busy) return;
  busy = true;
  render();
  try {
    const response = await chrome.runtime.sendMessage({ action });
    if (!response) throw new Error("Tidak ada respons dari Chrome Bridge.");
    state = response;
  } catch (error) {
    state = { ...state, error: String(error.message || error) };
  } finally {
    busy = false;
    render();
  }
}
async function poll() {
  if (busy) return;
  try {
    const response = await chrome.runtime.sendMessage({ action: "status" });
    if (response) { state = response; render(); }
  } catch (error) {
    state = { ...state, error: String(error.message || error) };
    render();
  }
}
$("approve").addEventListener("click", () => void act("approve"));
$("disconnect").addEventListener("click", () => void act("disconnect"));
setInterval(() => void poll(), 1500);
void poll();
