//! Executable models of Crabwalk's narrow generated unsafe/panic contracts.

use std::sync::atomic::{AtomicU64, Ordering};

static COUNTER: AtomicU64 = AtomicU64::new(0);

pub fn checked_atomic_increment(value: u64) -> Result<u64, &'static str> {
    let previous = COUNTER
        .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |current| {
            current.checked_add(value)
        })
        .map_err(|_| "counter overflow")?;
    previous.checked_add(value).ok_or("counter overflow")
}

pub fn checked_c_abs_input(value: i32) -> Result<i32, &'static str> {
    if value == i32::MIN {
        return Err("C abs is undefined for i32::MIN");
    }
    Ok(value.abs())
}

pub fn join_without_drop_panic(handles: Vec<std::thread::JoinHandle<()>>) {
    for handle in handles {
        let _ = handle.join();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn atomic_updates_are_race_free() {
        let before = COUNTER.load(Ordering::Relaxed);
        let workers: Vec<_> = (0..2)
            .map(|_| std::thread::spawn(|| checked_atomic_increment(1).unwrap()))
            .collect();
        for worker in workers {
            worker.join().unwrap();
        }
        assert_eq!(COUNTER.load(Ordering::Relaxed), before + 2);
    }

    #[test]
    fn c_abs_precondition_excludes_minimum() {
        assert_eq!(
            checked_c_abs_input(i32::MIN),
            Err("C abs is undefined for i32::MIN")
        );
        assert_eq!(checked_c_abs_input(-7), Ok(7));
    }

    #[test]
    fn joining_panicked_workers_does_not_panic_in_cleanup() {
        let worker = std::thread::spawn(|| panic!("worker failure"));
        join_without_drop_panic(vec![worker]);
    }
}
