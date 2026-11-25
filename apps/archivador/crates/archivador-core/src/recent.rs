//! The Recent place: the files the user opened lately, from wherever they are.

use std::collections::HashSet;
use std::ffi::OsString;
use std::os::unix::ffi::OsStringExt;
use std::path::{Path, PathBuf};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use crate::cloud;
use crate::entry::Entry;

/// What the desktop remembers about one recent file.
pub struct Item {
    pub path: PathBuf,
    pub visited: Option<SystemTime>,
}

/// How many recent files are shown. The desktop's list can hold thousands, each one costs a
/// look at the disk, and a window that stats them all before it draws anything seems stuck.
pub const LIMIT: usize = 200;

/// The files that are still there, newest visit first, as entries. Each one's time is when it was
/// last opened, not when it was last written, so sorting by it puts the newest visit first. Only
/// the newest [`LIMIT`] are looked at.
pub fn entries(items: impl IntoIterator<Item = Item>) -> Vec<Entry> {
    let mut items: Vec<Item> = items.into_iter().collect();
    items.sort_by_key(|item| std::cmp::Reverse(item.visited));
    let mut seen: HashSet<PathBuf> = HashSet::new();
    let mut out = Vec::new();
    for item in items {
        if out.len() >= LIMIT {
            break;
        }
        if !seen.insert(item.path.clone()) {
            continue;
        }
        if let Some(mut entry) = Entry::at(item.path) {
            if item.visited.is_some() {
                entry.modified = item.visited;
            }
            out.push(entry);
        }
    }
    out
}

/// Reads the desktop's list of recent files (`recently-used.xbel`) and returns the entries that
/// still exist. Meant for a worker thread: the file can be large and a file on a mount that has
/// gone away can take as long to look at as the network does. Files on a network or cloud mount
/// are not looked at at all. A missing or unreadable list is an empty one.
pub fn load(list: &Path) -> Vec<Entry> {
    let Ok(bytes) = std::fs::read(list) else {
        return Vec::new();
    };
    let remote = std::fs::read_to_string("/proc/self/mountinfo")
        .map(|info| cloud::remote_mounts(&info))
        .unwrap_or_default();
    let mut items = parse_xbel(&String::from_utf8_lossy(&bytes));
    items.retain(|item| !remote.iter().any(|mount| item.path.starts_with(mount)));
    entries(items)
}

/// The local files named by an XBEL list, with the time each was last visited. Files reached
/// through a network (anything but `file:` URIs) and through GVfs's FUSE mount are left out:
/// looking at them can wait on the network.
pub fn parse_xbel(text: &str) -> Vec<Item> {
    let mut items = Vec::new();
    let mut rest = text;
    while let Some(at) = rest.find("<bookmark") {
        rest = &rest[at + "<bookmark".len()..];
        // `<bookmark:applications>` and the like are other elements.
        if !rest.starts_with(|c: char| c.is_ascii_whitespace()) {
            continue;
        }
        let (mut href, mut visited, mut modified) = (None, None, None);
        let mut tag = rest;
        // The start tag ends at the first `>` outside quotes.
        loop {
            tag = tag.trim_start();
            if tag.is_empty() || tag.starts_with('>') || tag.starts_with("/>") {
                break;
            }
            let Some(eq) = tag.find('=') else { break };
            let name = tag[..eq].trim();
            let after = tag[eq + 1..].trim_start();
            let Some(quote) = after.chars().next().filter(|c| matches!(c, '"' | '\'')) else {
                break;
            };
            let Some(end) = after[1..].find(quote) else {
                break;
            };
            let value = &after[1..1 + end];
            match name {
                "href" => href = Some(value),
                "visited" => visited = Some(value),
                "modified" => modified = Some(value),
                _ => {}
            }
            tag = &after[end + 2..];
        }
        rest = tag;
        let Some(path) = href.and_then(|h| file_path(&unescape(h))) else {
            continue;
        };
        if path.components().any(|c| c.as_os_str() == "gvfs") {
            continue;
        }
        // A file that was only ever added has no visit; when it was last changed says as much.
        let when = visited.or(modified).and_then(parse_time);
        items.push(Item {
            path,
            visited: when,
        });
    }
    items
}

/// The path of a `file:` URI, if that is what it is and it names this machine.
fn file_path(uri: &str) -> Option<PathBuf> {
    let rest = uri.strip_prefix("file://")?;
    let path = rest.strip_prefix("localhost").unwrap_or(rest);
    if !path.starts_with('/') {
        return None;
    }
    let mut out = Vec::with_capacity(path.len());
    let bytes = path.as_bytes();
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'%' {
            let hex = path.get(i + 1..i + 3)?;
            out.push(u8::from_str_radix(hex, 16).ok()?);
            i += 3;
        } else {
            out.push(bytes[i]);
            i += 1;
        }
    }
    Some(PathBuf::from(OsString::from_vec(out)))
}

/// An XML attribute value with its entities (`&amp;`, `&#38;`…) resolved.
fn unescape(value: &str) -> String {
    if !value.contains('&') {
        return value.to_owned();
    }
    let mut out = String::with_capacity(value.len());
    let mut rest = value;
    while let Some(at) = rest.find('&') {
        out.push_str(&rest[..at]);
        rest = &rest[at..];
        let Some(end) = rest.find(';') else { break };
        let entity = &rest[1..end];
        let decoded = match entity {
            "amp" => Some('&'),
            "lt" => Some('<'),
            "gt" => Some('>'),
            "quot" => Some('"'),
            "apos" => Some('\''),
            _ => entity
                .strip_prefix("#x")
                .and_then(|h| u32::from_str_radix(h, 16).ok())
                .or_else(|| entity.strip_prefix('#').and_then(|d| d.parse().ok()))
                .and_then(char::from_u32),
        };
        match decoded {
            Some(c) => {
                out.push(c);
                rest = &rest[end + 1..];
            }
            None => {
                out.push('&');
                rest = &rest[1..];
            }
        }
    }
    out.push_str(rest);
    out
}

/// A time written as `2026-11-25T19:47:08.123456Z` (an offset such as `+01:00` works too).
fn parse_time(text: &str) -> Option<SystemTime> {
    let number = |range: std::ops::Range<usize>| -> Option<i64> { text.get(range)?.parse().ok() };
    if text.as_bytes().get(10) != Some(&b'T') {
        return None;
    }
    let (year, month, day) = (number(0..4)?, number(5..7)?, number(8..10)?);
    let (hour, minute, second) = (number(11..13)?, number(14..16)?, number(17..19)?);
    if !(1..=12).contains(&month) || !(1..=31).contains(&day) {
        return None;
    }
    // Days since 1970-01-01 (Howard Hinnant's civil-calendar algorithm).
    let y = if month <= 2 { year - 1 } else { year };
    let era = y.div_euclid(400);
    let yoe = y.rem_euclid(400);
    let doy = (153 * (month + if month > 2 { -3 } else { 9 }) + 2) / 5 + day - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    let days = era * 146_097 + doe - 719_468;
    let mut secs = days * 86_400 + hour * 3_600 + minute * 60 + second;
    // After the seconds come the fraction and then `Z` or the offset from UTC.
    let zone = text[19..].trim_start_matches(|c: char| c == '.' || c.is_ascii_digit());
    if let Some(sign) = zone.chars().next().filter(|c| matches!(c, '+' | '-')) {
        let (h, m) = (
            zone.get(1..3)?.parse::<i64>().ok()?,
            zone.get(4..6)?.parse::<i64>().ok()?,
        );
        let offset = h * 3_600 + m * 60;
        secs += if sign == '+' { -offset } else { offset };
    }
    UNIX_EPOCH.checked_add(Duration::from_secs(u64::try_from(secs).ok()?))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_list_is_read_without_the_network_or_the_other_elements() {
        let xbel = r#"<?xml version="1.0" encoding="UTF-8"?>
<xbel version="1.0">
  <bookmark href="file:///home/a/My%20File%20%C3%B1.txt" added="2026-11-25T19:47:08Z" modified="2026-11-25T19:47:08Z" visited="2026-11-25T19:47:09.5Z">
    <info><metadata owner="http://freedesktop.org">
      <bookmark:applications>
        <bookmark:application name="x" exec="&apos;x %u&apos;" count="1"/>
      </bookmark:applications>
    </metadata></info>
  </bookmark>
  <bookmark href="file:///tmp/a&amp;b.txt" modified="1970-01-02T00:00:00+01:00"/>
  <bookmark href="smb://server/share/c.txt" visited="2026-11-25T19:47:09Z"></bookmark>
  <bookmark href="file:///run/user/1000/gvfs/mtp:host=x/d.txt"></bookmark>
  <bookmark href="file://other-host/e.txt"></bookmark>
</xbel>"#;
        let items = parse_xbel(xbel);
        assert_eq!(items.len(), 2);
        assert_eq!(items[0].path, PathBuf::from("/home/a/My File ñ.txt"));
        assert_eq!(
            items[0].visited,
            Some(UNIX_EPOCH + Duration::from_secs(1_795_636_029))
        );
        assert_eq!(items[1].path, PathBuf::from("/tmp/a&b.txt"));
        // Midnight on the 2nd at +01:00 is 23:00 on the 1st UTC.
        assert_eq!(
            items[1].visited,
            Some(UNIX_EPOCH + Duration::from_secs(82_800))
        );
    }

    #[test]
    fn a_broken_list_does_not_panic() {
        for text in [
            "",
            "<bookmark",
            "<bookmark ",
            "<bookmark href",
            "<bookmark href=\"file:///x",
            "<bookmark href=\"file:///%zz\" visited=\"junk\">",
            "<bookmark href='file:///%'/>",
            "<bookmark href=\"file:///a&#99999999999;\" visited=\"9999999999999-01-01T00:00:00Z\"/>",
        ] {
            let _ = parse_xbel(text);
        }
    }

    #[test]
    fn a_big_list_is_read_quickly_and_only_the_newest_are_looked_at() {
        let dir =
            std::env::temp_dir().join(format!("archivador-recent-xbel-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let mut xbel = String::from("<xbel version=\"1.0\">\n");
        for i in 0..50_000u32 {
            xbel.push_str(&format!(
                "<bookmark href=\"file:///nonexistent/{i}.txt\" visited=\"2026-01-01T00:00:00Z\"><info/></bookmark>\n"
            ));
        }
        xbel.push_str("</xbel>");
        let list = dir.join("recently-used.xbel");
        std::fs::write(&list, xbel).unwrap();
        let started = std::time::Instant::now();
        assert!(load(&list).is_empty());
        let took = started.elapsed();
        std::fs::remove_dir_all(&dir).unwrap();
        assert!(took < Duration::from_secs(5), "took {took:?}");
        assert!(load(&dir.join("gone.xbel")).is_empty());
    }

    #[test]
    fn missing_files_and_repeats_are_left_out() {
        let dir = std::env::temp_dir().join(format!("archivador-recent-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let here = dir.join("a.txt");
        std::fs::write(&here, "x").unwrap();
        let visited = SystemTime::UNIX_EPOCH + Duration::from_secs(1_000_000);
        let found = entries([
            Item {
                path: here.clone(),
                visited: Some(visited),
            },
            Item {
                path: here.clone(),
                visited: None,
            },
            Item {
                path: dir.join("gone.txt"),
                visited: None,
            },
        ]);
        std::fs::remove_dir_all(&dir).unwrap();
        assert_eq!(found.len(), 1);
        assert_eq!(found[0].name, "a.txt");
        assert_eq!(found[0].modified, Some(visited));
    }

    #[test]
    fn only_the_newest_are_looked_at_and_they_come_newest_first() {
        let dir =
            std::env::temp_dir().join(format!("archivador-recent-many-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let items: Vec<Item> = (0..LIMIT as u64 + 20)
            .map(|i| {
                let path = dir.join(format!("{i}.txt"));
                std::fs::write(&path, "x").unwrap();
                Item {
                    path,
                    visited: Some(SystemTime::UNIX_EPOCH + std::time::Duration::from_secs(i)),
                }
            })
            .collect();
        let found = entries(items);
        std::fs::remove_dir_all(&dir).unwrap();
        assert_eq!(found.len(), LIMIT);
        assert_eq!(found[0].name, format!("{}.txt", LIMIT + 19));
        assert!(found.windows(2).all(|w| w[0].modified >= w[1].modified));
    }
}
