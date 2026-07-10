import { increment, count } from './state.js';

export function setupUI() {
  const btn = document.getElementById('btn');
  const display = document.getElementById('count');
  btn.addEventListener('click', () => {
    increment();
    display.textContent = String(count);
  });
}
