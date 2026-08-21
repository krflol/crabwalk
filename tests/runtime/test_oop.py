import sys
from crabwalk import rust

@rust.pyclass
class BankAccount:
    balance: rust.f64
    
    def __init__(self, initial_balance: rust.f64):
        self.balance = initial_balance
        
    def deposit(self, amount: rust.f64) -> rust.f64:
        self.balance = self.balance + amount
        return self.balance
        
    def withdraw(self, amount: rust.f64) -> rust.bool:
        if self.balance >= amount:
            self.balance = self.balance - amount
            return True
        return False

def test_oop():
    rust.compile(sys.modules[__name__])
    
    acc = BankAccount(100.50)
    assert acc.balance == 100.50
    
    new_bal = acc.deposit(50.25)
    assert new_bal == 150.75
    assert acc.balance == 150.75
    
    success = acc.withdraw(200.0)
    assert not success
    assert acc.balance == 150.75
    
    success = acc.withdraw(50.0)
    assert success
    assert acc.balance == 100.75
