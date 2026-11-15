//! Tokens in the macOS Keychain: generic passwords, service `peek`, account = token key. (Task 4)
use crate::fetch::TokenStore;
use std::io;

pub struct Keychain;

impl TokenStore for Keychain {
    fn get(&self, _key: &str) -> Option<String> {
        None
    }
    fn set(&self, _key: &str, _value: &str) -> io::Result<()> {
        Err(io::ErrorKind::Unsupported.into())
    }
}
