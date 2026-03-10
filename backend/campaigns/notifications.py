"""
Firebase integration for real-time notifications.
Uses Firebase Admin SDK to push events to Firestore
which the frontend can listen to via the Firebase JS SDK.
"""
import logging

logger = logging.getLogger(__name__)

# Flag to track if firebase is initialized
_firebase_initialized = False

def _init_firebase():
    """Initialize Firebase Admin SDK (lazy, one-time)."""
    global _firebase_initialized
    if _firebase_initialized:
        return True
    try:
        import firebase_admin
        from firebase_admin import credentials
        
        # For development, use default credentials or a service account
        # In production, set GOOGLE_APPLICATION_CREDENTIALS env var
        if not firebase_admin._apps:
            firebase_admin.initialize_app()
        _firebase_initialized = True
        return True
    except Exception as e:
        logger.warning(f"Firebase not configured (OK for dev): {e}")
        return False

def send_notification(organization_id, event_type, payload):
    """
    Send a real-time notification event to Firestore.
    Frontend clients listen to the organization's notification subcollection.
    
    Args:
        organization_id: UUID of the organization
        event_type: Type of event (e.g., 'lead_imported', 'campaign_started', 'email_bounced')
        payload: Dict with event-specific data
    """
    if not _init_firebase():
        logger.info(f"[MOCK NOTIFICATION] org={organization_id} type={event_type} data={payload}")
        return
    
    try:
        from firebase_admin import firestore
        from datetime import datetime
        
        db = firestore.client()
        doc_ref = db.collection('organizations').document(str(organization_id))
        notifications_ref = doc_ref.collection('notifications')
        
        notifications_ref.add({
            'type': event_type,
            'payload': payload,
            'read': False,
            'created_at': datetime.utcnow().isoformat(),
        })
        
        logger.info(f"Firebase notification sent: {event_type} for org {organization_id}")
    except Exception as e:
        logger.error(f"Failed to send Firebase notification: {e}")

# Convenience functions for common events
def notify_lead_imported(organization_id, count):
    send_notification(organization_id, 'lead_imported', {
        'message': f'{count} leads imported successfully',
        'count': count
    })

def notify_campaign_activated(organization_id, campaign_name):
    send_notification(organization_id, 'campaign_activated', {
        'message': f'Campaign "{campaign_name}" is now active',
        'campaign': campaign_name
    })

def notify_email_bounced(organization_id, lead_email):
    send_notification(organization_id, 'email_bounced', {
        'message': f'Email bounced for {lead_email}',
        'email': lead_email
    })

def notify_reply_received(organization_id, lead_email):
    send_notification(organization_id, 'reply_received', {
        'message': f'Reply received from {lead_email}',
        'email': lead_email
    })
