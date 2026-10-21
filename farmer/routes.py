"""API for signup, mock OTP login, profile and document checks.

Auth: after OTP login the browser sends `Authorization: Bearer <token>`.
Every auth/document event is written to the evidence log (OTP/token redacted, mobile masked).
"""
from typing import Optional

from fastapi import APIRouter, File, Header, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from farmer import accounts, doccheck, samples

router = APIRouter(prefix="/api")
EVIDENCE = {"log": None}     # set by server.py so events land in the same evidence log


def _log(step, who, **data):
    if EVIDENCE["log"] is not None:
        EVIDENCE["log"].log(f"farmer-{who}", step, **data)


def _token(authorization):
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


def account_error_handler(request: Request, exc: accounts.AccountError):
    return JSONResponse(status_code=exc.status,
                        content={"error": exc.code, "message": exc.message, **exc.extra})


class SignupIn(BaseModel):
    name: Optional[str] = None
    mobile: Optional[str] = None
    village: Optional[str] = None
    district: Optional[str] = None
    land_acres: Optional[str] = None
    main_crop: Optional[str] = None


class OtpRequestIn(BaseModel):
    mobile: str


class OtpVerifyIn(BaseModel):
    mobile: str
    otp: str


@router.post("/auth/signup")
def signup(body: SignupIn):
    res = accounts.signup(body.model_dump())
    _log("signup", res["farmer_id"], mobile=res["mobile_masked"], result="created")
    return res


@router.post("/auth/otp/request")
def otp_request(body: OtpRequestIn):
    res = accounts.request_otp(body.mobile)
    _log("otp_request", res["sent_to"], sent_to=res["sent_to"], otp=res["mock_otp"])   # otp gets redacted
    return res


@router.post("/auth/otp/verify")
def otp_verify(body: OtpVerifyIn):
    try:
        token, fid = accounts.verify_otp(body.mobile, body.otp)
    except accounts.AccountError as exc:
        _log("otp_verify", accounts.mask_mobile(accounts.extract_digits(body.mobile) or "0000000000"),
             result=exc.code)
        raise
    _log("otp_verify", fid, result="logged_in", token=token)                             # token gets redacted
    return {"token": token, "profile": accounts.profile(fid)}


@router.post("/auth/logout")
def logout(authorization: Optional[str] = Header(None)):
    accounts.logout(_token(authorization))
    return {"ok": True}


@router.get("/profile")
def get_profile(authorization: Optional[str] = Header(None)):
    return accounts.profile(accounts.farmer_for_token(_token(authorization)))


@router.post("/profile/documents/{doc_type}")
async def upload_document(doc_type: str, file: UploadFile = File(...),
                          authorization: Optional[str] = Header(None)):
    fid = accounts.farmer_for_token(_token(authorization))
    content = await file.read(doccheck.MAX_BYTES + 1)     # never read more than the limit + 1
    result = accounts.save_document(fid, doc_type, file.filename, content)
    _log("document_check", fid, doc_type=doc_type, file_name=file.filename, status=result["status"],
         failed=[c["name"] for c in result["checks"] if not c["ok"]])
    return {"result": result, "profile": accounts.profile(fid)}


@router.get("/samples")
def list_samples():
    return {"samples": samples.sample_list(), "doc_types": accounts.DOC_TYPES}
