from solders.pubkey import Pubkey
from solders.instruction import AccountMeta, Instruction

# The dedicated "jitodontfront" public key used to signal searchers.
# In actual Jito/MEV setups, adding this key as a read-only, non-signer account 
# alerts block engines to flag and prevent sandwiching of the payload.
JITO_DONT_FRONT_PUBKEY = Pubkey.from_string("96gYZ2y6xtJ6nt6WUx44yKWcWXFn2Fc14D9wZ1Dkhm7K") # Standard jitodontfront pubkey representation

class SandwichProtection:
    @staticmethod
    def inject_protection(instruction: Instruction) -> Instruction:
        """
        Injects the 'jitodontfront' read-only pubkey into the instruction's keys list
        to notify searchers and block engines to block sandwich attacks.
        """
        meta = AccountMeta(
            pubkey=JITO_DONT_FRONT_PUBKEY,
            is_signer=False,
            is_writable=False
        )
        
        # Inject as the very first account meta in the instruction
        new_accounts = [meta] + list(instruction.accounts)
        
        return Instruction(
            program_id=instruction.program_id,
            data=instruction.data,
            accounts=new_accounts
        )
