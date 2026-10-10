"""Decode SPL mint bytes and conservatively inventory Token-2022 TLVs.

Layout/IDs: solana-program/token-2022, interface/src/extension/mod.rs. Only
metadata pointer and token metadata are admitted. Metadata URIs are never fetched.
"""
import base64
import binascii
import struct

from collectors.http import DataUnavailable

TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
EXTENSIONS = {
    1: "transferFeeConfig", 2: "transferFeeAmount", 3: "mintCloseAuthority",
    4: "confidentialTransferMint", 5: "confidentialTransferAccount", 6: "defaultAccountState",
    7: "immutableOwner", 8: "memoTransfer", 9: "nonTransferable", 10: "interestBearingConfig",
    11: "cpiGuard", 12: "permanentDelegate", 13: "nonTransferableAccount", 14: "transferHook",
    15: "transferHookAccount", 16: "confidentialTransferFeeConfig", 17: "confidentialTransferFeeAmount",
    18: "metadataPointer", 19: "tokenMetadata", 20: "groupPointer", 21: "tokenGroup",
    22: "groupMemberPointer", 23: "tokenGroupMember", 24: "confidentialMintBurn",
    25: "scaledUiAmount", 26: "pausable", 27: "pausableAccount", 28: "permissionedBurn",
}


def address_bytes(value: str) -> bytes:
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    try:
        number = 0
        for char in value:
            number = number * 58 + alphabet.index(char)
        result = b"\0" * (len(value) - len(value.lstrip("1"))) + number.to_bytes((number.bit_length() + 7) // 8, "big")
        if len(result) != 32:
            raise ValueError
        return result
    except (ValueError, OverflowError):
        raise DataUnavailable("Invalid mint address") from None


def _metadata_valid(data: bytes, mint: bytes) -> bool:
    if len(data) < 64 or data[32:64] != mint:
        return False
    offset = 64
    try:
        def string():
            nonlocal offset
            length = struct.unpack_from("<I", data, offset)[0]
            offset += 4
            if length > len(data) - offset:
                raise ValueError
            data[offset:offset + length].decode("utf-8")
            offset += length
        for _ in range(3):
            string()
        count = struct.unpack_from("<I", data, offset)[0]
        offset += 4
        if count > (len(data) - offset) // 8:
            return False
        for _ in range(count):
            string()
            string()
        return offset == len(data)
    except (ValueError, struct.error, UnicodeDecodeError):
        return False


def decode_mint(account: dict, token: str) -> dict:
    owner = account.get("owner")
    result = {"program_id": owner, "supported_program": owner in (TOKEN_PROGRAM, TOKEN_2022_PROGRAM)}
    if not result["supported_program"]:
        return result
    try:
        encoded = account["data"]
        if not isinstance(encoded, list) or len(encoded) != 2 or encoded[1] != "base64":
            raise ValueError
        raw = base64.b64decode(encoded[0], validate=True)
        if len(raw) < 82 or raw[45] != 1 or len(raw) == 355:
            raise ValueError
        mint_option = struct.unpack_from("<I", raw, 0)[0]
        freeze_option = struct.unpack_from("<I", raw, 46)[0]
        if mint_option not in (0, 1) or freeze_option not in (0, 1):
            raise ValueError
        supply = struct.unpack_from("<Q", raw, 36)[0]
        if owner == TOKEN_PROGRAM and len(raw) != 82:
            raise ValueError
        result.update(mint_authority=bool(mint_option), freeze_authority=bool(freeze_option),
                      raw_supply=str(supply), extension_names=[], extension_reasons=[],
                      extension_checks_passed=True, metadata_mutable=False)
        if owner == TOKEN_PROGRAM or len(raw) == 82:
            return result
        if len(raw) < 166 or raw[165] != 1 or any(raw[82:165]):
            raise ValueError
        offset, seen = 166, set()
        while offset < len(raw):
            if not any(raw[offset:]):
                break
            kind, length = struct.unpack_from("<HH", raw, offset)
            offset += 4
            if kind == 0 or kind in seen or length > len(raw) - offset:
                raise ValueError
            seen.add(kind)
            payload = raw[offset:offset + length]
            offset += length
            name = EXTENSIONS.get(kind, f"unknown_{kind}")
            result["extension_names"].append(name)
            if kind == 18:
                if len(payload) != 64:
                    raise ValueError
                result["metadata_mutable"] |= any(payload[:32])
            elif kind == 19:
                if not _metadata_valid(payload, address_bytes(token)):
                    raise ValueError
                result["metadata_mutable"] |= any(payload[:32])
            else:
                result["extension_reasons"].append(f"unsupported_extension:{name}")
        result["extension_checks_passed"] = not result["extension_reasons"]
        return result
    except (KeyError, ValueError, TypeError, struct.error, binascii.Error):
        raise DataUnavailable("Malformed or unparseable mint account") from None
