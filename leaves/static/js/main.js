/* ============================================
   LeaveTrack Pro — Main JS
   ============================================ */

document.addEventListener('DOMContentLoaded', () => {
  initMobileNav();
  initDayCalculator();
  initSuccessModal();
  initLeaveTabs();
});

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
  const tabs = document.querySelectorAll('.tab[data-filter]');
  const rows = document.querySelectorAll('#my-leaves-body tr');

  if (!tabs.length || !rows.length) return;

  tabs.forEach((tab) => {
    tab.addEventListener('click', () => {
      tabs.forEach((t) => t.classList.remove('active'));
      tab.classList.add('active');

      const filter = tab.dataset.filter;
      rows.forEach((row) => {
        row.style.display = (filter === 'all' || row.dataset.status === filter) ? '' : 'none';
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