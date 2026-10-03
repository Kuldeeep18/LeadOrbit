from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from tenants.models import TenantModel
from django.core.signing import Signer

class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('Users must have an email address')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        # ─── FIX: Set is_active to True for superusers ───
        extra_fields.setdefault('is_active', True)
        return self.create_user(email, password, **extra_fields)

class User(AbstractBaseUser, PermissionsMixin, TenantModel):
    ROLE_ADMIN = 'ADMIN'
    ROLE_MANAGER = 'MANAGER'
    ROLE_MEMBER = 'MEMBER'
    ROLE_LEGACY_USER = 'USER'

    ROLE_CHOICES = (
        (ROLE_ADMIN, 'Admin'),
        (ROLE_MANAGER, 'Manager'),
        (ROLE_MEMBER, 'Member'),
        (ROLE_LEGACY_USER, 'User'),
    )
    email = models.EmailField(unique=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_MEMBER)
    
    # ─── CRITICAL SECURITY FIX: Users inactive until email verification ───
    # Changed default from True to False (Fix #616)
    is_active = models.BooleanField(default=False)
    
    is_staff = models.BooleanField(default=False)

    # ─── CRITICAL SECURITY FIX: Two-Factor Authentication (Fix #628) ───
    has_2fa = models.BooleanField(default=False)
    # ─── FIX: Store encrypted OTP secret instead of plain text ───
    otp_secret_encrypted = models.TextField(blank=True, null=True)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['organization']

    def __str__(self):
        return self.email

    # ─── Helper methods for encrypted OTP secret ───
    def set_otp_secret(self, secret):
        """Encrypt and store OTP secret"""
        if secret:
            signer = Signer(salt='user.otp_secret')
            self.otp_secret_encrypted = signer.sign(secret)
        else:
            self.otp_secret_encrypted = None

    def get_otp_secret(self):
        """Decrypt and return OTP secret"""
        if not self.otp_secret_encrypted:
            return None
        try:
            signer = Signer(salt='user.otp_secret')
            return signer.unsign(self.otp_secret_encrypted)
        except:
            return None

            