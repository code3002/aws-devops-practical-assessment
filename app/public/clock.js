async function refresh() {
  try {
    const response = await fetch('/time', { cache: 'no-store' });
    if (!response.ok) return;
    const data = await response.json();
    document.querySelector('#clock').textContent = data.timestamp;
  } catch { /* Keep the last known timestamp during a network interruption. */ }
}
refresh();
setInterval(refresh, 1000);
