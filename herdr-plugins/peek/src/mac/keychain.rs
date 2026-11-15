//! Tokens in the macOS Keychain: generic passwords, service `peek`, account = token key.
use crate::fetch::TokenStore;
use security_framework::passwords::{generic_password, set_generic_password, PasswordOptions};
use std::io;

const SERVICE: &str = "peek";

pub struct Keychain;

impl TokenStore for Keychain {
    fn get(&self, key: &str) -> Option<String> {
        let secret = generic_password(PasswordOptions::new_generic_password(SERVICE, key)).ok()?;
        String::from_utf8(secret).ok()
    }

    /// Creates the item or replaces its secret.
    fn set(&self, key: &str, value: &str) -> io::Result<()> {
        set_generic_password(SERVICE, key, value.as_bytes()).map_err(|e| io::Error::other(e.to_string()))
    }
}
