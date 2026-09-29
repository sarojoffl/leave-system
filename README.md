# Leave & Attendance Management System

A full-featured HR Management, Attendance Tracking, and Leave Administration System built with **Django 6** and **Python 3**. The system includes seamless **Bikram Sambat (BS) & Gregorian (AD)** calendar support, **ZKTeco Biometric Device (Push Protocol / ADDK)** integration, multi-stop **Staff Movement** tracking with PDF generation, automated **email password resets**, and a mobile-optimized responsive interface.

---

## 🌟 Key Features

### 1. 📅 Attendance & Biometric Integration
- **Biometric Push Protocol**: Native `/iclock/` endpoint compatible with ZKTeco ADMS/ADDK push devices (real-time punch logging via device user ID/PIN).
- **Dual Calendar View**: Monthly attendance rendered in **Bikram Sambat (BS)** with AD date mappings.
- **Punch Intelligence**:
  - Automatically identifies first punch (In) and last punch (Out).
  - Late arrival detection (after 10:15 AM threshold).
  - Daily duration and overtime (OT) computation.
  - Flags missing punches (`⚠️ In` / `⚠️ Out`).
- **Responsive Views**:
  - **Desktop View**: Rich detailed cards showing status pills, in/out timestamps, duration, and overtime tags.
  - **Mobile View**: 100% width, no-scroll 7-column calendar with micro-badges and punch times. Tap any cell to view the full day timeline modal.
  - **List View**: Chronological day-by-day punch breakdown.
- **Attendance Regularization**: Request attendance corrections for missed punches.
- **Holiday Work Requests**: Log work done on public holidays or weekends for comp-off credit.

### 2. 🏖️ Leave Management
- **Leave Types & Balances**: Annual leave entitlements, sick leave, casual leave, and compensatory off (comp-off) tracking.
- **Multi-Day Leave Applications**: Working day calculation automatically excluding Saturdays and applicable public holidays.
- **Role-Based Approvals**: Two-tier approval workflows (Manager / Admin / CEO) with decision notes.
- **Public Holidays**: Configurable holiday calendars supporting gender-specific holidays (e.g., Teej / Jitiya Parva for female employees).

### 3. 🚗 Staff Movement (Field Visits)
- **Multi-Stop Tracking**: Log field visits with multiple client stops, entry/exit times, and vehicle odometer readings.
- **Assistant Delegation**: Link accompanying team members / assistants to movements.
- **Departmental Work Logging**: Record internal and cross-department field tasks.
- **Status Lifecycle**: `in_field` ➔ `completed` with return-time logging.
- **PDF Export**: Generate professional formatted field movement reports using ReportLab.

### 4. 👤 User Accounts & Role-Based Access Control
- **Custom User Model**: Roles include `Employee`, `Manager`, `System Administrator`, and `CEO`.
- **Profile Self-Service**: Employees can update basic information (name, email, gender) while keeping employment metadata read-only.
- **Password Reset via Email**: Modern, responsive HTML email template for self-service password resets.
- **First-Time Password Change**: Mandatory password change enforcement on initial login.

### 5. 📊 Dashboard & Reports
- **Executive Analytics**: Real-time metrics on present staff, late arrivals, active leaves, and pending requests.
- **Visual Trends**: Monthly leave trends and comp-off utilization charts.
- **Manager Delegation**: Managers can switch employee views to inspect team attendance.

---

## 🏗️ Tech Stack

- **Backend**: Python 3.11+, Django 6.0
- **Database**: SQLite (default / development), MySQL / PostgreSQL (production via `.env`)
- **Reporting**: ReportLab 5.0 (PDF exports), Pillow (image handling)
- **Frontend**: HTML5, CSS3 (Custom Responsive Design System), Vanilla JavaScript, Remix Icon
- **Environment**: `python-dotenv` for configuration management

---

## 🚀 Getting Started

### Prerequisites
- Python 3.11 or higher
- `git`
- Virtual environment tool (`venv`)

### Installation & Setup

1. **Clone the Repository**:
   ```bash
   git clone <repository-url>
   cd leave_system
   ```

2. **Create and Activate a Virtual Environment**:
   ```bash
   python3 -m venv venv
   source venv/bin/activate   # On Windows: venv\Scripts\activate
   ```

3. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure Environment Variables**:
   Create a `.env` file in the root directory:
   ```env
   DEBUG=True
   SECRET_KEY=your-secret-key-here
   ALLOWED_HOSTS=127.0.0.1,localhost
   TIME_ZONE=Asia/Kathmandu

   # Database (defaults to SQLite if omitted)
   DB_ENGINE=django.db.backends.sqlite3
   DB_NAME=db.sqlite3

   # Email Configuration (for password reset)
   EMAIL_HOST=smtp.example.com
   EMAIL_PORT=465
   EMAIL_USE_SSL=True
   EMAIL_USE_TLS=False
   EMAIL_HOST_USER=no-reply@example.com
   EMAIL_HOST_PASSWORD=your-email-password
   DEFAULT_FROM_EMAIL="Leave System <no-reply@example.com>"
   ```

5. **Run Migrations**:
   ```bash
   python manage.py migrate
   ```

6. **Create a Superuser**:
   ```bash
   python manage.py createsuperuser
   ```

7. **Start the Development Server**:
   ```bash
   python manage.py runserver
   ```
   Access the application at `http://127.0.0.1:8000/`.

---

## 🧪 Running Automated Tests

Run the full test suite across all apps (`accounts`, `leaves`, `dashboard`):
```bash
python manage.py test accounts leaves dashboard
```

---

## 📁 Project Structure

```
leave_system/
│
├── accounts/               # User authentication, profile, roles, password reset
│   ├── templates/accounts/ # Login, profile, and password reset email templates
│   ├── forms.py            # User profile and custom password reset forms
│   ├── middleware.py       # Force password change enforcement
│   ├── models.py           # Custom User model
│   └── views.py            # Profile & password reset authentication views
│
├── leaves/                 # Leave requests, attendance, biometrics, staff movements
│   ├── templates/leaves/   # Attendance calendar, leave requests, staff movements
│   ├── nepali_calendar.py  # Bikram Sambat (BS) to AD date converters
│   ├── models.py           # AttendanceLog, BiometricDevice, LeaveRequest, StaffMovement
│   ├── views.py            # Attendance logic, leave approvals, movement logger, PDF export
│   └── iclock_views.py     # ZKTeco ADMS push protocol endpoint (/iclock/)
│
├── dashboard/              # Analytics, team statistics, and reporting views
├── leave_system/           # Django project root settings, wsgi, and master urls
├── staticfiles/            # Collected static files for production
├── manage.py
├── requirements.txt
└── README.md
```

---

## 📱 Biometric Device Configuration (ZKTeco ADMS)

To connect a ZKTeco biometric device to the system:
1. Access the device's **Communication / Cloud Server / ADMS** settings.
2. Set **Server Address**: Your server IP or domain (e.g., `https://your-domain.com`).
3. Set **Server Port**: `80` (HTTP) or `443` (HTTPS).
4. Set **Push Protocol**: ADMS / iClock enabled.
5. In the admin dashboard, ensure the employee's **Device User ID** matches their biometric PIN / Badge number.
