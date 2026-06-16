# Email setup

## Quick start (development)

No setup needed. By default, emails go to `noop` provider and are logged to
`email_log` table only. Run `tail -f` on logs to see what would have been sent.

## Production setup (when domain is ready)

1. Buy domain (e.g., `contaneta.com`).
2. Create Resend account at https://resend.com.
3. Add domain in Resend dashboard.
4. Add the SPF/DKIM/DMARC records Resend gives you to your DNS provider.
5. Wait for verification (~15 min).
6. Generate Resend API key.
7. Set these env vars:

   ```
   RESEND_API_KEY=re_xxx
   EMAIL_FROM_ADDRESS=facturas@contaneta.com
   EMAIL_FROM_NAME=ContaNeta
   EMAIL_SUPPORT_ADDRESS=soporte@contaneta.com
   ```

8. (Optional) Configure webhook in Resend dashboard:
   - URL: `https://yourapp.com/api/webhooks/resend`
   - Events: `email.delivered`, `email.opened`, `email.bounced`, `email.complained`
   - Copy webhook secret to `RESEND_WEBHOOK_SECRET`.

9. Restart app. Verify provider with: `python -c "from services.email.config import get_provider_name; print(get_provider_name())"` (should print `resend`).

10. Test with:
    ```python
    from services.email.sender import send_email
    send_email(to_email='tu@correo.com', template='welcome', context={'user_name': 'Test'})
    ```
