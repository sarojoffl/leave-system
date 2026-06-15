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

  // Close sidebar when a nav link is tapped (mobile)
  sidebar.querySelectorAll('.nav-item').forEach((link) => {
    link.addEventListener('click', () => {
      if (window.innerWidth <= 768) closeSidebar();
    });
  });
}

/* ------------------------------------------
   Apply Leave: live "calculated days" field
------------------------------------------- */
function initDayCalculator() {
  const fromInput = document.getElementById('from-date');
  const toInput = document.getElementById('to-date');
  const durationSelect = document.getElementById('duration');
  const output = document.getElementById('calc-days');

  if (!fromInput || !toInput || !output) return;

  const calc = () => {
    const from = fromInput.value;
    const to = toInput.value;
    const duration = durationSelect ? durationSelect.value : 'full';

    if (!from || !to) {
      output.value = '';
      return;
    }

    if (duration === 'am' || duration === 'pm') {
      output.value = '0.5 day';
      return;
    }

    const f = new Date(from);
    const t = new Date(to);
    const diff = Math.round((t - f) / 86400000) + 1;

    output.value = diff > 0
      ? `${diff} ${diff === 1 ? 'day' : 'days'}`
      : 'Invalid range';
  };

  fromInput.addEventListener('change', calc);
  toInput.addEventListener('change', calc);
  if (durationSelect) durationSelect.addEventListener('change', calc);
}

/* ------------------------------------------
   Success modal (after leave submission)
   Server renders #modal-bg with .open class
   and #modal-summary content when
   show_success_modal is set in session.
------------------------------------------- */
function initSuccessModal() {
  const modalBg = document.getElementById('modal-bg');
  const closeBtn = document.getElementById('modal-close-btn');
  const doneBtn = document.getElementById('modal-done-btn');

  if (!modalBg) return;

  const close = () => modalBg.classList.remove('open');

  if (closeBtn) closeBtn.addEventListener('click', close);
  if (doneBtn) doneBtn.addEventListener('click', close);

  modalBg.addEventListener('click', (e) => {
    if (e.target === modalBg) close();
  });
}

/* ------------------------------------------
   My Leaves: client-side status tabs
   Tabs filter rows by data-status attribute
   without a page reload.
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
        if (filter === 'all' || row.dataset.status === filter) {
          row.style.display = '';
        } else {
          row.style.display = 'none';
        }
      });
    });
  });
}

/* ------------------------------------------
   Confirm before destructive actions
   (cancel leave, reject leave forms)
------------------------------------------- */
document.addEventListener('submit', (e) => {
  const form = e.target;
  if (form.matches('.confirm-cancel')) {
    if (!confirm('Cancel this leave request?')) {
      e.preventDefault();
    }
  }
});
