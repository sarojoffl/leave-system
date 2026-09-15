"""
iClock protocol views for ZKTeco biometric device integration.

The ZKTeco device pushes attendance data to these endpoints via HTTP.
These views are csrf_exempt because the device cannot send CSRF tokens.
"""
import logging
from datetime import datetime

from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .models import AttendanceLog, BiometricDevice

logger = logging.getLogger(__name__)
User = get_user_model()


@csrf_exempt
def iclock_cdata(request):
    """
    /iclock/cdata — Main webhook endpoint for ZKTeco device.

    GET:  Device handshake / connectivity check. Returns OK.
    POST: Device pushes attendance data (ATTLOG table).
          Query params: SN (device serial), table (ATTLOG/OPERLOG)
          Body: tab-separated attendance records, one per line.
          Format: PIN\tTimestamp\tStatus\tVerifyMode\tWorkCode
    """
    serial = request.GET.get('SN', '')
    table = request.GET.get('table', '')

    if request.method == 'GET':
        # Device handshake — just acknowledge
        logger.info(f"ZKTeco GET handshake: SN={serial}")
        return HttpResponse("OK")

    if request.method == 'POST':
        raw_data = request.body.decode('utf-8', errors='ignore')
        logger.info(f"ZKTeco POST: SN={serial}, Table={table}")
        logger.info(f"Raw:\n{raw_data}")

        # Auto-register or update device
        device = None
        if serial:
            device, created = BiometricDevice.objects.get_or_create(
                serial_number=serial,
                defaults={'name': f'Device {serial}'}
            )
            device.last_seen = timezone.now()
            device.save(update_fields=['last_seen'])
            if created:
                logger.info(f"Auto-registered new device: {serial}")

        # Process attendance log data
        if table == 'ATTLOG':
            _process_attlog(raw_data, device)

        return HttpResponse(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Response><Status>OK</Status></Response>',
            content_type="application/xml"
        )

    return HttpResponse("OK")


def _process_attlog(raw_data, device):
    """
    Parse ATTLOG lines and create AttendanceLog records.
    Each line format: PIN\tTimestamp\tStatus\tVerifyMode\tWorkCode
    Example: 1\t2026-09-14 10:00:00\t0\t1\t0
    """
    # Build a lookup of device_user_id → User for quick matching
    user_map = {}
    for uid, user_id in User.objects.filter(
        device_user_id__isnull=False
    ).values_list('device_user_id', 'id'):
        user_map[str(uid)] = user_id

    created_count = 0
    skipped_count = 0

    for line in raw_data.strip().splitlines():
        line = line.strip()
        if not line:
            continue

        parts = line.split('\t')
        if len(parts) < 2:
            logger.warning(f"Skipping malformed ATTLOG line: {line!r}")
            continue

        pin = parts[0].strip()
        timestamp_str = parts[1].strip()
        status = int(parts[2].strip()) if len(parts) > 2 else 0
        verify_mode = int(parts[3].strip()) if len(parts) > 3 else None
        work_code = parts[4].strip() if len(parts) > 4 else ''

        try:
            punch_time = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
            # Make timezone-aware
            punch_time = timezone.make_aware(punch_time, timezone.get_current_timezone())
        except (ValueError, TypeError) as e:
            logger.warning(f"Skipping ATTLOG line with bad timestamp: {line!r} — {e}")
            continue

        # Resolve employee from PIN
        employee_id = user_map.get(pin)

        # Create record (skip duplicates via unique_together)
        _, created = AttendanceLog.objects.get_or_create(
            device_user_id=pin,
            timestamp=punch_time,
            device=device,
            defaults={
                'employee_id': employee_id,
                'status': status,
                'verify_mode': verify_mode,
                'work_code': work_code,
                'raw_data': line,
            }
        )

        if created:
            created_count += 1
            employee_label = f"User#{employee_id}" if employee_id else f"PIN={pin}(unmapped)"
            logger.info(f"Attendance: {employee_label} punched {status} at {punch_time}")
        else:
            skipped_count += 1

    logger.info(f"ATTLOG processed: {created_count} new, {skipped_count} duplicates skipped")


@csrf_exempt
def iclock_getrequest(request):
    """
    /iclock/getrequest — Device polls for pending commands.
    Returns OK (no commands). Placeholder for future command support
    (e.g., restart device, sync users, clear logs).
    """
    serial = request.GET.get('SN', '')
    logger.debug(f"ZKTeco getrequest poll: SN={serial}")
    return HttpResponse("OK")


@csrf_exempt
def iclock_devicecmd(request):
    """
    /iclock/devicecmd — Device posts command execution results.
    """
    serial = request.GET.get('SN', '')
    logger.debug(f"ZKTeco devicecmd: SN={serial}")
    return HttpResponse("OK")

