/* ============================================
   LeaveTrack Pro — Main JS
   ============================================ */

document.addEventListener('DOMContentLoaded', () => {
  initMobileNav();
  initDayCalculator();
  initSuccessModal();
  initLeaveTabs();
  initThemeToggle();
});

/* ------------------------------------------
   Theme toggle (dark / light)
   Preference persisted in localStorage so it
   sticks across pages and visits. The actual
   class is applied early via an inline script
   in base.html's <head> to avoid a flash.
------------------------------------------- */
function initThemeToggle() {
  const toggle = document.getElementById('theme-toggle');
  if (!toggle) return;

  const STORAGE_KEY = 'leavetrack-theme';
  const root = document.documentElement;

  toggle.addEventListener('click', () => {
    const isLight = root.getAttribute('data-theme') === 'light';
    if (isLight) {
      root.removeAttribute('data-theme');
      localStorage.setItem(STORAGE_KEY, 'dark');
    } else {
      root.setAttribute('data-theme', 'light');
      localStorage.setItem(STORAGE_KEY, 'light');
    }
  });
}

/* ------------------------------------------
   Mobile sidebar / hamburger
------------------------------------------- */
function initMobileNav() {
  const hamburger = document.getElementById('hamburger');
  const sidebar = document.getElementById('sidebar');
  const overlay = document.getElementById('sidebar-overlay');
  const closeBtn = document.getElementById('sidebar-close');

  if (!hamburger || !sidebar || !overlay) return;

  const openSidebar = () => {
    sidebar.classList.add('open');
    overlay.classList.add('open');
  };

  const closeSidebar = () => {
    sidebar.classList.remove('open');
    overlay.classList.remove('open');
  };

  hamburger.addEventListener('click', openSidebar);
  overlay.addEventListener('click', closeSidebar);
  if (closeBtn) closeBtn.addEventListener('click', closeSidebar);

  sidebar.querySelectorAll('.nav-item').forEach((link) => {
    link.addEventListener('click', () => {
      if (window.innerWidth <= 768) closeSidebar();
    });
  });
}

/* ------------------------------------------
   Apply Leave: live "calculated days" field
   Excludes Saturdays. Public holidays are
   excluded server-side and may reduce the
   final count further.
------------------------------------------- */
function initDayCalculator() {
  const fromInput = document.getElementById('from-date');
  const toInput   = document.getElementById('to-date');
  const output    = document.getElementById('calc-days');

  if (!fromInput || !toInput || !output) return;

  function parseLocalDate(str) {
    const [y, m, d] = str.split('-').map(Number);
    return new Date(y, m - 1, d);
  }

  function countWorkingDays(from, to) {
    let count = 0;
    const cur = new Date(from);
    while (cur <= to) {
      if (cur.getDay() !== 6) count++;  // exclude Saturday
      cur.setDate(cur.getDate() + 1);
    }
    return count;
  }

  const calc = () => {
    const from = fromInput.value;
    const to   = toInput.value;

    if (!from || !to) { output.value = ''; return; }

    const fromDate = parseLocalDate(from);
    const toDate   = parseLocalDate(to);

    if (toDate < fromDate) { output.value = 'Invalid range'; return; }

    const days = countWorkingDays(fromDate, toDate);
    output.value = days + (days === 1 ? ' day' : ' days');
  };

  fromInput.addEventListener('change', calc);
  toInput.addEventListener('change', calc);
}

/* ------------------------------------------
   Success modal (after leave submission)
------------------------------------------- */
function initSuccessModal() {
  const modalBg = document.getElementById('modal-bg');
  const closeBtn = document.getElementById('modal-close-btn');
  const doneBtn  = document.getElementById('modal-done-btn');

  if (!modalBg) return;

  const close = () => modalBg.classList.remove('open');

  if (closeBtn) closeBtn.addEventListener('click', close);
  if (doneBtn)  doneBtn.addEventListener('click', close);

  modalBg.addEventListener('click', (e) => {
    if (e.target === modalBg) close();
  });
}

/* ------------------------------------------
   My Leaves: client-side status tabs
------------------------------------------- */
function initLeaveTabs() {
  const panels = document.querySelectorAll('.type-panel');
  if (!panels.length) return;

  panels.forEach((panel) => {
    const tabs = panel.querySelectorAll('.tabs .tab[data-filter]');
    const rows = panel.querySelectorAll('tbody tr');
    const exportBtn = panel.querySelector('.flex-actions a[id^="export-"]');

    if (!tabs.length || !rows.length) return;

    // Show/hide export button initially based on active tab
    const activeTab = panel.querySelector('.tabs .tab.active');
    const initialFilter = activeTab ? activeTab.dataset.filter : 'all';
    if (exportBtn) {
      exportBtn.style.display = initialFilter === 'approved' ? '' : 'none';
    }

    tabs.forEach((tab) => {
      tab.addEventListener('click', () => {
        tabs.forEach((t) => t.classList.remove('active'));
        tab.classList.add('active');

        const filter = tab.dataset.filter;
        rows.forEach((row) => {
          if (row.querySelector('.empty-state') || row.classList.contains('empty-state')) {
            return;
          }
          row.style.display = (filter === 'all' || row.dataset.status === filter) ? '' : 'none';
        });

        if (exportBtn) {
          exportBtn.style.display = filter === 'approved' ? '' : 'none';
        }
      });
    });
  });
}

/* ------------------------------------------
   Confirm before destructive actions
------------------------------------------- */
document.addEventListener('submit', (e) => {
  const form = e.target;
  if (form.matches('.confirm-cancel')) {
    if (!confirm('Cancel this leave request?')) e.preventDefault();
  }
});