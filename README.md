# LG RMA Hub - public-safe copy

This copy retains the troubleshooting and device reference tools but excludes customer records and internal contact details:

- The RMA JSON exports are not included, and RMA lookup is disabled.
- Email addresses and phone numbers in troubleshooting content have been removed.
- No local SMTP secrets are included.

The original working copy and its local RMA records are unchanged. Review the troubleshooting material and reference images for business-information disclosure before making this copy public.

## Run locally

```text
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

The login gate allows the Omnidian and Solar Service Guys email domains configured in `auth.py`. It uses email OTP; configure SMTP credentials in `.streamlit/secrets.toml` from `secrets.toml.example`, or in the hosting provider's secret manager. Never commit SMTP secrets.

Streamlit Community Cloud's public setting allows anyone to open the app URL. The email-domain allowlist is enforced by this app's login code; it is not a platform-level domain access rule. For sensitive records, use private app sharing or an approved company-authenticated host.
