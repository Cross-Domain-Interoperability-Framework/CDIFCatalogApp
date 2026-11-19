# Setting up the ORCID and DOI test environments

Written 17 November 2026 from ORCID's and DataCite's own documentation, linked in each section.
Check those pages if a step no longer matches what you see.

## What needs an account and what does not

| Feature | Service | Account needed? |
|---|---|---|
| Find an organisation | ROR | No |
| Fill the form from a DOI | DataCite, then Crossref | No. It reads public records. |
| Find a person by name or iD | ORCID public search | Works without one today. ORCID's documentation says credentials are required, so register a client before anyone outside the team uses this. |
| Sign in with ORCID, which harvesting requires | ORCID | Yes: a Public API client. |
| Mint DOIs for records (not in the design) | DataCite | Yes: a DataCite member or repository account. |

So the only setup needed for the next step of the prototype is the ORCID sandbox client.

## ORCID sandbox

The sandbox is a separate copy of ORCID holding only test data. Accounts and credentials made
there do not exist on the real ORCID, and the reverse.
Source: [Sandbox testing server](https://info.orcid.org/documentation/integration-guide/sandbox-testing-server/),
[How do I register a Public API client?](https://info.orcid.org/ufaqs/how-do-i-register-a-public-api-client/)

### 1. Create a sandbox account

1. Go to https://sandbox.orcid.org/register and register. This is a new account; your real ORCID
   sign-in does not work here.
2. Verify the email address. Developer Tools stay locked until you do: the terms-of-service
   tick box and the **Register for your ORCID Public API credentials** button are greyed out.

   **Check this before you register:** as far as we recall, the sandbox only delivers email to
   `@mailinator.com` addresses, which are public throwaway inboxes read at https://www.mailinator.com.
   This is from memory, not from the pages above. If no verification email arrives at your own
   address, register again with a made-up `something@mailinator.com` address.

### 2. Register a Public API client

1. Sign in at https://sandbox.orcid.org/signin.
2. Click your name at the top right, then **Developer Tools**.
3. Read and accept the ORCID Public APIs Terms of Service, then click
   **Register for ORCID Public API Credentials**.
4. Fill in the application details. Users see these on the permission screen.
   - **Name:** `CDIF Catalog (test)`
   - **Application URL:** `https://github.com/Cross-Domain-Interoperability-Framework/CDIFCatalogApp`
   - **Description:** for example, "Prototype catalog for CDIF metadata. Uses your ORCID iD to
     sign you in and attach your records to you."
5. Add the redirect URI. This is where ORCID sends the user back after they approve.
   - For a developer machine: `http://127.0.0.1:5173/api/auth/orcid/callback`

     Not `localhost`: ORCID's form answers "Invalid redirect URL" to an address containing
     `localhost` (seen 19 November 2026). `127.0.0.1` is the same machine by number.
   - For the test sessions, add the HTTPS address of the test server with the same path.

   The address must match exactly, including the port and path. It is the catalog's own address
   (`PUBLIC_URL`) followed by `/api/auth/orcid/callback`.

   An account has one Public API client, and one client can list several redirect URIs. If the
   account already has a client for another application, add this address to it and use the same
   credentials here, accepting that both applications then show the same name on ORCID's
   permission screen.
6. Click **Save my application and generate my client ID and secret**.

Developer Tools now shows a **Client ID** (looks like `APP-XXXXXXXXXXXXXXXX`) and a **Client secret**.

Two things from ORCID's documentation:

- The credentials belong to the individual account that registered them.
- You can edit the application details and redirect URIs later from the same page.

### 3. Give the credentials to the application

Create a file named `.env` in the repository root. It is listed in `.gitignore` and must never be
committed.

```
ORCID_BASE=https://sandbox.orcid.org
ORCID_CLIENT_ID=APP-XXXXXXXXXXXXXXXX
ORCID_CLIENT_SECRET=paste-the-secret-here
ADMIN_ORCIDS=0000-0000-0000-0000
```

`ADMIN_ORCIDS` lists the ORCID iDs of the people who are admins, separated by commas. Use sandbox
iDs with the sandbox. A person named there becomes an admin the next time they sign in. Only
admins can register and run harvest sources.

Then restart the server so it reads the file: `docker compose up -d api worker`.

Treat the secret like a password: do not put it in chat, email, an issue or a commit.

A fifth setting, `ORCID_API_BASE=https://pub.sandbox.orcid.org`, switches the author search to
the sandbox. The sandbox holds only test people, so with it set, searching for a real researcher
finds nothing. Leave it out to keep searching real ORCID records while signing in through the
sandbox.

Treat the first sign-in as a test of the code: it has only ever run against a stand-in for ORCID.

### 4. Make test users

Register two or three more sandbox accounts to sign in as. Give them public names and an
affiliation so they also show up in person search against the sandbox.

### Moving to the real ORCID later

Repeat step 2 at https://orcid.org/signin. Differences: production accepts only `https://`
redirect URIs, and the credentials are tied to the real ORCID record of whoever registers them, so
choose that person deliberately. Organisations that are ORCID members use their member credentials
instead.

## DOIs

### Filling the form from a DOI needs no setup

The DOI box reads the public record from DataCite and, if DataCite does not have it, from
Crossref. Neither needs an account, a key or a sandbox.

### DataCite's test system: only needed to create DOIs

DataCite runs a test copy of its services for trying out DOI registration without creating real
DOIs. Source: [DataCite Testing Guide](https://support.datacite.org/docs/testing-guide)

- **Who can have a test account:** current DataCite Members and Repositories, and potential new
  Members. An individual cannot simply sign up. If your organisation is a DataCite member or works
  through a consortium, ask its DataCite contact for a test repository account; otherwise follow
  "Get a test account" in the guide above.
- **Test services:** Fabrica at https://doi.test.datacite.org, REST API at https://api.test.datacite.org.
- **Test DOIs are not real.** They do not resolve at https://doi.org; they look like
  `https://handle.test.datacite.org/10.17596/w76y-4s92`.

The catalog design does not include minting DOIs, so none of this is needed unless that changes.

To make the DOI box look up DOIs in DataCite's test system instead of the real one, set this in `.env`:

```
DATACITE_API_BASE=https://api.test.datacite.org
```

Reading from the test system needs no account either.

### Crossref

No test environment is needed for reading. Crossref asks heavy users to identify themselves with a
contact email on each request; the application does not send one, which is fine at prototype volume.
