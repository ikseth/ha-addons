//go:build windows

package com

import (
	"context"
	"fmt"
	"runtime"
	"strings"
	"syscall"
	"unsafe"

	"golang.org/x/sys/windows"
)

const (
	coinitMultithreaded = 0
	clsctxInprocServer  = 1

	dispatchMethod        = 1
	dispatchPropertyGet   = 2
	dispatchPropertyPut   = 4
	dispatchIDPropertyPut = -3
	localeSystemDefault   = 0x0800

	vtEmpty    = 0
	vtNull     = 1
	vtI2       = 2
	vtI4       = 3
	vtR4       = 4
	vtR8       = 5
	vtBSTR     = 8
	vtDispatch = 9
	vtBool     = 11
	vtVariant  = 12
	vtUnknown  = 13
	vtDecimal  = 14
	vtI1       = 16
	vtUI1      = 17
	vtUI2      = 18
	vtUI4      = 19
	vtI8       = 20
	vtUI8      = 21
	vtInt      = 22
	vtUint     = 23
	vtArray    = 0x2000

	rpcCAuthnWinNT          = 10
	rpcCAuthzNone           = 0
	rpcCAuthnLevelDefault   = 0
	rpcCAuthnLevelCall      = 3
	rpcCImpLevelImpersonate = 3
	eoacNone                = 0

	wbemFlagReturnImmediately         = 0x10
	wbemFlagForwardOnly               = 0x20
	wbemNoError                       = 0
	wbemFalse                         = 1
	wbemTimedOut                      = 0x00040004
	rpcETooLate               hresult = 0x80010119
)

var (
	ole32    = windows.NewLazySystemDLL("ole32.dll")
	oleaut32 = windows.NewLazySystemDLL("oleaut32.dll")

	procCoInitializeEx       = ole32.NewProc("CoInitializeEx")
	procCoUninitialize       = ole32.NewProc("CoUninitialize")
	procCoInitializeSecurity = ole32.NewProc("CoInitializeSecurity")
	procCLSIDFromProgID      = ole32.NewProc("CLSIDFromProgID")
	procCoCreateInstance     = ole32.NewProc("CoCreateInstance")
	procCoSetProxyBlanket    = ole32.NewProc("CoSetProxyBlanket")
	procSysAllocString       = oleaut32.NewProc("SysAllocString")
	procSysFreeString        = oleaut32.NewProc("SysFreeString")
	procVariantClear         = oleaut32.NewProc("VariantClear")
	procSafeArrayGetLBound   = oleaut32.NewProc("SafeArrayGetLBound")
	procSafeArrayGetUBound   = oleaut32.NewProc("SafeArrayGetUBound")
	procSafeArrayGetElement  = oleaut32.NewProc("SafeArrayGetElement")

	iidNull          = windows.GUID{}
	iidIDispatch     = windows.GUID{Data1: 0x00020400, Data4: [8]byte{0xc0, 0, 0, 0, 0, 0, 0, 0x46}}
	clsidWbemLocator = windows.GUID{Data1: 0x4590f811, Data2: 0x1d3a, Data3: 0x11d0, Data4: [8]byte{0x89, 0x1f, 0, 0xaa, 0, 0x4b, 0x2e, 0x24}}
	iidIWbemLocator  = windows.GUID{Data1: 0xdc12a687, Data2: 0x737f, Data3: 0x11cf, Data4: [8]byte{0x88, 0x4d, 0, 0xaa, 0, 0x4b, 0x2e, 0x24}}
)

type hresult uint32

func (value hresult) failed() bool { return value&0x80000000 != 0 }

func (value hresult) String() string {
	return fmt.Sprintf("HRESULT 0x%08X (%d): %s", uint32(value), int32(value), syscall.Errno(value).Error())
}

func hrError(operation string, value hresult) error {
	return fmt.Errorf("%s failed: %s", operation, value)
}

type variant struct {
	VT       uint16
	Reserved [3]uint16
	Value    [2]uintptr
}

type dispParams struct {
	Args            *variant
	NamedArgIDs     *int32
	ArgCount        uint32
	NamedArgIDCount uint32
}

type exceptionInfo struct {
	Code           uint16
	Reserved       uint16
	Source         *uint16
	Description    *uint16
	HelpFile       *uint16
	HelpContext    uint32
	Private        uintptr
	DeferredFillIn uintptr
	SCode          int32
}

type iDispatch struct{ VTable *[7]uintptr }
type iWbemLocator struct{ VTable *[4]uintptr }
type iWbemServices struct{ VTable *[21]uintptr }
type iEnumWbemClassObject struct{ VTable *[8]uintptr }
type iWbemClassObject struct{ VTable *[5]uintptr }

func inApartment(ctx context.Context, operation func() error) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	runtime.LockOSThread()
	defer runtime.UnlockOSThread()
	hr := hresult(call(procCoInitializeEx, 0, coinitMultithreaded))
	if hr.failed() {
		return hrError("CoInitializeEx(COINIT_MULTITHREADED)", hr)
	}
	defer procCoUninitialize.Call()
	security := hresult(call(procCoInitializeSecurity, 0, ^uintptr(0), 0, 0, rpcCAuthnLevelDefault, rpcCImpLevelImpersonate, 0, eoacNone, 0))
	if security.failed() && security != rpcETooLate {
		return hrError("CoInitializeSecurity", security)
	}
	return operation()
}

func queryUpdates(ctx context.Context, scope string) (snapshot UpdateSnapshot, err error) {
	err = inApartment(ctx, func() error {
		session, createErr := createDispatch("Microsoft.Update.Session")
		if createErr != nil {
			return createErr
		}
		defer session.release()
		searcher, invokeErr := session.dispatch("CreateUpdateSearcher", dispatchMethod)
		if invokeErr != nil {
			return invokeErr
		}
		defer searcher.release()
		if putErr := searcher.putBool("Online", true); putErr != nil {
			return putErr
		}
		if scope == "managed" {
			if putErr := searcher.putInt32("ServerSelection", 1); putErr != nil {
				return putErr
			}
		}
		criterion, allocErr := newBSTRVariant("IsInstalled=0 AND IsHidden=0")
		if allocErr != nil {
			return allocErr
		}
		defer criterion.clear()
		result, searchErr := searcher.dispatch("Search", dispatchMethod, criterion)
		if searchErr != nil {
			return searchErr
		}
		defer result.release()
		updates, updatesErr := result.dispatch("Updates", dispatchPropertyGet)
		if updatesErr != nil {
			return updatesErr
		}
		defer updates.release()
		count, countErr := updates.uint32("Count")
		if countErr != nil {
			return countErr
		}
		snapshot.Packages = make([]UpdatePackage, 0, count)
		for index := uint32(0); index < count; index++ {
			if contextErr := ctx.Err(); contextErr != nil {
				return contextErr
			}
			item, itemErr := updates.dispatch("Item", dispatchPropertyGet, int32Variant(int32(index)))
			if itemErr != nil {
				return fmt.Errorf("IUpdateCollection.Item(%d): %w", index, itemErr)
			}
			pack, packErr := readUpdate(item)
			item.release()
			if packErr != nil {
				return fmt.Errorf("read update %d: %w", index, packErr)
			}
			snapshot.Packages = append(snapshot.Packages, pack)
		}
		systemInfo, systemErr := createDispatch("Microsoft.Update.SystemInfo")
		if systemErr != nil {
			return systemErr
		}
		defer systemInfo.release()
		snapshot.RebootRequired, systemErr = systemInfo.boolean("RebootRequired")
		return systemErr
	})
	return snapshot, err
}

func readUpdate(update *iDispatch) (UpdatePackage, error) {
	title, err := update.string("Title")
	if err != nil {
		return UpdatePackage{}, err
	}
	severity, err := update.optionalString("MsrcSeverity")
	if err != nil {
		return UpdatePackage{}, err
	}
	size, err := update.uint64("MaxDownloadSize")
	if err != nil {
		return UpdatePackage{}, err
	}
	kb, err := firstCollectionString(update, "KBArticleIDs")
	if err != nil {
		return UpdatePackage{}, err
	}
	if kb != "" && !strings.HasPrefix(strings.ToUpper(kb), "KB") {
		kb = "KB" + kb
	}
	security, err := updateIsSecurity(update, severity)
	if err != nil {
		return UpdatePackage{}, err
	}
	return UpdatePackage{Title: title, KB: kb, Severity: severity, SizeBytes: size, IsSecurity: security}, nil
}

func firstCollectionString(parent *iDispatch, property string) (string, error) {
	collection, err := parent.dispatch(property, dispatchPropertyGet)
	if err != nil {
		return "", err
	}
	defer collection.release()
	count, err := collection.uint32("Count")
	if err != nil || count == 0 {
		return "", err
	}
	item, err := collection.invoke("Item", dispatchPropertyGet, int32Variant(0))
	if err != nil {
		return "", err
	}
	defer item.clear()
	return item.asString()
}

func updateIsSecurity(update *iDispatch, severity string) (bool, error) {
	if severity != "" {
		return true, nil
	}
	categories, err := update.dispatch("Categories", dispatchPropertyGet)
	if err != nil {
		return false, err
	}
	defer categories.release()
	count, err := categories.uint32("Count")
	if err != nil {
		return false, err
	}
	for index := uint32(0); index < count; index++ {
		category, itemErr := categories.dispatch("Item", dispatchPropertyGet, int32Variant(int32(index)))
		if itemErr != nil {
			return false, itemErr
		}
		categoryID, idErr := category.string("CategoryID")
		name, nameErr := category.string("Name")
		category.release()
		if idErr != nil {
			return false, idErr
		}
		if nameErr != nil {
			return false, nameErr
		}
		switch strings.ToLower(categoryID) {
		case "0fa1201d-4330-4fa8-8ae9-b877473b6441", // Security Updates
			"e6cf1350-c01b-414d-a61f-263d14d133b4", // Critical Updates
			"e0789628-ce08-4437-be74-2495b842f43b": // Definition Updates
			return true, nil
		}
		normalized := strings.ToLower(name)
		if strings.Contains(normalized, "security") || strings.Contains(normalized, "critical update") || strings.Contains(normalized, "definition update") {
			return true, nil
		}
	}
	return false, nil
}

func queryDefender(ctx context.Context) (status DefenderStatus, err error) {
	err = queryWMI(ctx, `root\Microsoft\Windows\Defender`, "SELECT AntivirusEnabled, RealTimeProtectionEnabled, AntivirusSignatureAge, AntivirusSignatureVersion, QuickScanEndTime FROM MSFT_MpComputerStatus", func(object *iWbemClassObject) error {
		var readErr error
		status.AntivirusEnabled, readErr = object.boolean("AntivirusEnabled")
		if readErr != nil {
			return readErr
		}
		status.RealtimeProtectionEnabled, readErr = object.boolean("RealTimeProtectionEnabled")
		if readErr != nil {
			return readErr
		}
		status.SignatureAgeDays, readErr = object.uint32("AntivirusSignatureAge")
		if readErr != nil {
			return readErr
		}
		status.SignatureVersion, readErr = object.string("AntivirusSignatureVersion")
		if readErr != nil {
			return readErr
		}
		status.LastQuickScan, readErr = object.optionalString("QuickScanEndTime")
		return readErr
	})
	return status, err
}

func queryBitLocker(ctx context.Context) (volumes []BitLockerVolume, err error) {
	volumes = make([]BitLockerVolume, 0)
	err = queryWMI(ctx, `root\CIMV2\Security\MicrosoftVolumeEncryption`, "SELECT DriveLetter, ProtectionStatus, ConversionStatus, EncryptionMethod FROM Win32_EncryptableVolume", func(object *iWbemClassObject) error {
		drive, readErr := object.optionalString("DriveLetter")
		if readErr != nil {
			return readErr
		}
		protection, readErr := object.uint32("ProtectionStatus")
		if readErr != nil {
			return readErr
		}
		conversion, readErr := object.uint32("ConversionStatus")
		if readErr != nil {
			return readErr
		}
		method, readErr := object.uint32("EncryptionMethod")
		if readErr != nil {
			return readErr
		}
		volumes = append(volumes, BitLockerVolume{DriveLetter: drive, ProtectionStatus: protection, ConversionStatus: conversion, EncryptionMethod: method})
		return nil
	})
	return volumes, err
}

func createDispatch(progID string) (*iDispatch, error) {
	name, err := windows.UTF16PtrFromString(progID)
	if err != nil {
		return nil, err
	}
	var class windows.GUID
	hr := hresult(call(procCLSIDFromProgID, uintptr(unsafe.Pointer(name)), uintptr(unsafe.Pointer(&class))))
	if hr.failed() {
		return nil, hrError("CLSIDFromProgID("+progID+")", hr)
	}
	var result *iDispatch
	hr = hresult(call(procCoCreateInstance, uintptr(unsafe.Pointer(&class)), 0, clsctxInprocServer, uintptr(unsafe.Pointer(&iidIDispatch)), uintptr(unsafe.Pointer(&result))))
	if hr.failed() {
		return nil, hrError("CoCreateInstance("+progID+")", hr)
	}
	if result == nil {
		return nil, fmt.Errorf("CoCreateInstance(%s) returned a nil IDispatch", progID)
	}
	return result, nil
}

func (object *iDispatch) putInt32(name string, value int32) error {
	argument := int32Variant(value)
	named := int32(dispatchIDPropertyPut)
	result, err := object.invokeWithNamed(name, dispatchPropertyPut, []variant{argument}, &named)
	result.clear()
	return err
}

func (object *iDispatch) putBool(name string, value bool) error {
	argument := variant{VT: vtBool}
	if value {
		argument.Value[0] = uintptr(^uint16(0))
	}
	named := int32(dispatchIDPropertyPut)
	result, err := object.invokeWithNamed(name, dispatchPropertyPut, []variant{argument}, &named)
	result.clear()
	return err
}

func (object *iDispatch) dispatch(name string, flags uint16, arguments ...variant) (*iDispatch, error) {
	value, err := object.invoke(name, flags, arguments...)
	if err != nil {
		return nil, err
	}
	defer value.clear()
	if value.VT == vtDispatch {
		result := (*iDispatch)(value.pointer())
		value.VT, value.Value[0] = vtEmpty, 0
		if result == nil {
			return nil, fmt.Errorf("IDispatch::Invoke(%s) returned nil VT_DISPATCH", name)
		}
		return result, nil
	}
	if value.VT == vtUnknown {
		unknown := value.pointer()
		if unknown == nil {
			return nil, fmt.Errorf("IDispatch::Invoke(%s) returned nil VT_UNKNOWN", name)
		}
		return queryIDispatch(unknown, name)
	}
	return nil, fmt.Errorf("IDispatch::Invoke(%s) returned VARIANT type %d, expected dispatch", name, value.VT)
}

func (object *iDispatch) invoke(name string, flags uint16, arguments ...variant) (variant, error) {
	return object.invokeWithNamed(name, flags, arguments, nil)
}

func (object *iDispatch) invokeWithNamed(name string, flags uint16, arguments []variant, named *int32) (variant, error) {
	dispatchID, err := object.dispID(name)
	if err != nil {
		return variant{}, err
	}
	params := dispParams{}
	if len(arguments) > 0 {
		reversed := make([]variant, len(arguments))
		for index := range arguments {
			reversed[len(arguments)-1-index] = arguments[index]
		}
		params.Args, params.ArgCount = &reversed[0], uint32(len(reversed))
	}
	if named != nil {
		params.NamedArgIDs, params.NamedArgIDCount = named, 1
	}
	var result variant
	var exception exceptionInfo
	var argumentError uint32
	hr := hresult(vtableCall(object.VTable[6], uintptr(unsafe.Pointer(object)), uintptr(dispatchID), uintptr(unsafe.Pointer(&iidNull)), localeSystemDefault, uintptr(flags), uintptr(unsafe.Pointer(&params)), uintptr(unsafe.Pointer(&result)), uintptr(unsafe.Pointer(&exception)), uintptr(unsafe.Pointer(&argumentError))))
	if hr.failed() {
		result.clear()
		detail := exception.text()
		exception.clear()
		return variant{}, fmt.Errorf("IDispatch::Invoke(%s, DISPID %d) failed: %s; argument %d%s", name, dispatchID, hr, argumentError, detail)
	}
	exception.clear()
	return result, nil
}

func (object *iDispatch) dispID(name string) (int32, error) {
	pointer, err := windows.UTF16PtrFromString(name)
	if err != nil {
		return 0, err
	}
	var result int32
	hr := hresult(vtableCall(object.VTable[5], uintptr(unsafe.Pointer(object)), uintptr(unsafe.Pointer(&iidNull)), uintptr(unsafe.Pointer(&pointer)), 1, localeSystemDefault, uintptr(unsafe.Pointer(&result))))
	if hr.failed() {
		return 0, hrError("IDispatch::GetIDsOfNames("+name+")", hr)
	}
	return result, nil
}

func (object *iDispatch) string(name string) (string, error) {
	value, err := object.invoke(name, dispatchPropertyGet)
	if err != nil {
		return "", err
	}
	defer value.clear()
	return value.asString()
}

func (object *iDispatch) optionalString(name string) (string, error) {
	value, err := object.invoke(name, dispatchPropertyGet)
	if err != nil {
		return "", err
	}
	defer value.clear()
	if value.VT == vtEmpty || value.VT == vtNull {
		return "", nil
	}
	return value.asString()
}

func (object *iDispatch) boolean(name string) (bool, error) {
	value, err := object.invoke(name, dispatchPropertyGet)
	if err != nil {
		return false, err
	}
	defer value.clear()
	return value.asBool()
}

func (object *iDispatch) uint32(name string) (uint32, error) {
	value, err := object.invoke(name, dispatchPropertyGet)
	if err != nil {
		return 0, err
	}
	defer value.clear()
	return value.asUint32()
}

func (object *iDispatch) uint64(name string) (uint64, error) {
	value, err := object.invoke(name, dispatchPropertyGet)
	if err != nil {
		return 0, err
	}
	defer value.clear()
	return value.asUint64()
}

func queryIDispatch(unknown unsafe.Pointer, source string) (*iDispatch, error) {
	vtable := *(*unsafe.Pointer)(unknown)
	method := (*[3]uintptr)(vtable)[0]
	var result *iDispatch
	hr := hresult(vtableCall(method, uintptr(unknown), uintptr(unsafe.Pointer(&iidIDispatch)), uintptr(unsafe.Pointer(&result))))
	if hr.failed() {
		return nil, hrError("QueryInterface(IID_IDispatch) for "+source, hr)
	}
	if result == nil {
		return nil, fmt.Errorf("QueryInterface(IID_IDispatch) for %s returned nil", source)
	}
	return result, nil
}

func queryWMI(ctx context.Context, namespace, query string, visit func(*iWbemClassObject) error) error {
	return inApartment(ctx, func() error {
		locator, err := createWbemLocator()
		if err != nil {
			return err
		}
		defer locator.release()
		services, err := locator.connect(namespace)
		if err != nil {
			return err
		}
		defer services.release()
		enumerator, err := services.query(query)
		if err != nil {
			return err
		}
		defer enumerator.release()
		found := false
		for {
			if contextErr := ctx.Err(); contextErr != nil {
				return contextErr
			}
			object, done, nextErr := enumerator.next(1000)
			if nextErr != nil {
				return nextErr
			}
			if done {
				break
			}
			if object == nil {
				continue
			}
			found = true
			visitErr := visit(object)
			object.release()
			if visitErr != nil {
				return visitErr
			}
		}
		if !found {
			return fmt.Errorf("WMI query returned no objects: %s", query)
		}
		return nil
	})
}

func createWbemLocator() (*iWbemLocator, error) {
	var locator *iWbemLocator
	hr := hresult(call(procCoCreateInstance, uintptr(unsafe.Pointer(&clsidWbemLocator)), 0, clsctxInprocServer, uintptr(unsafe.Pointer(&iidIWbemLocator)), uintptr(unsafe.Pointer(&locator))))
	if hr.failed() {
		return nil, hrError("CoCreateInstance(CLSID_WbemLocator)", hr)
	}
	if locator == nil {
		return nil, fmt.Errorf("CoCreateInstance(CLSID_WbemLocator) returned nil")
	}
	return locator, nil
}

func (locator *iWbemLocator) connect(namespace string) (*iWbemServices, error) {
	name, err := allocBSTR(namespace)
	if err != nil {
		return nil, err
	}
	defer freeBSTR(name)
	var services *iWbemServices
	hr := hresult(vtableCall(locator.VTable[3], uintptr(unsafe.Pointer(locator)), name, 0, 0, 0, 0, 0, 0, uintptr(unsafe.Pointer(&services))))
	if hr.failed() {
		return nil, hrError("IWbemLocator::ConnectServer("+namespace+")", hr)
	}
	if services == nil {
		return nil, fmt.Errorf("IWbemLocator::ConnectServer(%s) returned nil", namespace)
	}
	hr = hresult(call(procCoSetProxyBlanket, uintptr(unsafe.Pointer(services)), rpcCAuthnWinNT, rpcCAuthzNone, 0, rpcCAuthnLevelCall, rpcCImpLevelImpersonate, 0, eoacNone))
	if hr.failed() {
		services.release()
		return nil, hrError("CoSetProxyBlanket("+namespace+")", hr)
	}
	return services, nil
}

func (services *iWbemServices) query(query string) (*iEnumWbemClassObject, error) {
	language, err := allocBSTR("WQL")
	if err != nil {
		return nil, err
	}
	defer freeBSTR(language)
	statement, err := allocBSTR(query)
	if err != nil {
		return nil, err
	}
	defer freeBSTR(statement)
	var result *iEnumWbemClassObject
	hr := hresult(vtableCall(services.VTable[20], uintptr(unsafe.Pointer(services)), language, statement, wbemFlagReturnImmediately|wbemFlagForwardOnly, 0, uintptr(unsafe.Pointer(&result))))
	if hr.failed() {
		return nil, hrError("IWbemServices::ExecQuery("+query+")", hr)
	}
	if result == nil {
		return nil, fmt.Errorf("IWbemServices::ExecQuery returned nil")
	}
	return result, nil
}

func (enumerator *iEnumWbemClassObject) next(timeout uint32) (*iWbemClassObject, bool, error) {
	var object *iWbemClassObject
	var returned uint32
	hr := hresult(vtableCall(enumerator.VTable[4], uintptr(unsafe.Pointer(enumerator)), uintptr(timeout), 1, uintptr(unsafe.Pointer(&object)), uintptr(unsafe.Pointer(&returned))))
	if hr == wbemTimedOut {
		return nil, false, nil
	}
	if hr == wbemFalse || (hr == wbemNoError && returned == 0) {
		return nil, true, nil
	}
	if hr.failed() {
		return nil, false, hrError("IEnumWbemClassObject::Next", hr)
	}
	if returned == 0 || object == nil {
		return nil, true, nil
	}
	return object, false, nil
}

func (object *iWbemClassObject) get(name string) (variant, error) {
	pointer, err := windows.UTF16PtrFromString(name)
	if err != nil {
		return variant{}, err
	}
	var result variant
	hr := hresult(vtableCall(object.VTable[4], uintptr(unsafe.Pointer(object)), uintptr(unsafe.Pointer(pointer)), 0, uintptr(unsafe.Pointer(&result)), 0, 0))
	if hr.failed() {
		result.clear()
		return variant{}, hrError("IWbemClassObject::Get("+name+")", hr)
	}
	return result, nil
}

func (object *iWbemClassObject) boolean(name string) (bool, error) {
	value, err := object.get(name)
	if err != nil {
		return false, err
	}
	defer value.clear()
	return value.asBool()
}
func (object *iWbemClassObject) uint32(name string) (uint32, error) {
	value, err := object.get(name)
	if err != nil {
		return 0, err
	}
	defer value.clear()
	return value.asUint32()
}
func (object *iWbemClassObject) string(name string) (string, error) {
	value, err := object.get(name)
	if err != nil {
		return "", err
	}
	defer value.clear()
	return value.asString()
}
func (object *iWbemClassObject) optionalString(name string) (string, error) {
	value, err := object.get(name)
	if err != nil {
		return "", err
	}
	defer value.clear()
	if value.VT == vtEmpty || value.VT == vtNull {
		return "", nil
	}
	return value.asString()
}

func int32Variant(value int32) variant { return variant{VT: vtI4, Value: [2]uintptr{uintptr(value)}} }

func newBSTRVariant(value string) (variant, error) {
	pointer, err := allocBSTR(value)
	if err != nil {
		return variant{}, err
	}
	return variant{VT: vtBSTR, Value: [2]uintptr{pointer}}, nil
}

func (value *variant) pointer() unsafe.Pointer {
	return *(*unsafe.Pointer)(unsafe.Pointer(&value.Value[0]))
}

func (value variant) asString() (string, error) {
	if value.VT != vtBSTR {
		return "", fmt.Errorf("unexpected VARIANT type %d, expected VT_BSTR", value.VT)
	}
	if value.Value[0] == 0 {
		return "", nil
	}
	return windows.UTF16PtrToString((*uint16)((&value).pointer())), nil
}

func (value variant) asBool() (bool, error) {
	if value.VT != vtBool {
		return false, fmt.Errorf("unexpected VARIANT type %d, expected VT_BOOL", value.VT)
	}
	return int16(value.Value[0]) != 0, nil
}

func (value variant) asUint32() (uint32, error) {
	switch value.VT {
	case vtI1, vtUI1, vtI2, vtUI2, vtI4, vtUI4, vtInt, vtUint:
		return uint32(value.Value[0]), nil
	default:
		return 0, fmt.Errorf("unexpected VARIANT type %d, expected integer", value.VT)
	}
}

func (value variant) asUint64() (uint64, error) {
	switch value.VT {
	case vtI1, vtUI1, vtI2, vtUI2, vtI4, vtUI4, vtInt, vtUint:
		return uint64(value.Value[0]), nil
	case vtI8, vtUI8:
		result := uint64(value.Value[0])
		if unsafe.Sizeof(uintptr(0)) == 4 {
			result |= uint64(value.Value[1]) << 32
		}
		return result, nil
	case vtDecimal:
		// DECIMAL overlays the complete VARIANT. At offsets 2..7 it stores
		// scale/sign and Hi32, while offsets 8..15 contain Lo64.
		scale := byte(value.Reserved[0])
		sign := byte(value.Reserved[0] >> 8)
		hi := uint32(value.Reserved[1]) | uint32(value.Reserved[2])<<16
		lo := uint64(value.Value[0])
		if unsafe.Sizeof(uintptr(0)) == 4 {
			lo |= uint64(value.Value[1]) << 32
		}
		if sign != 0 || hi != 0 {
			return 0, fmt.Errorf("DECIMAL value does not fit in uint64")
		}
		for range scale {
			lo /= 10
		}
		return lo, nil
	default:
		return 0, fmt.Errorf("unexpected VARIANT type %d, expected integer", value.VT)
	}
}

// stringArray owns no memory. The caller must keep the source VARIANT alive and
// clear it after the returned strings have been copied.
func (value variant) stringArray() ([]string, error) {
	if value.VT != vtArray|vtBSTR && value.VT != vtArray|vtVariant {
		return nil, fmt.Errorf("unexpected VARIANT type %d, expected SAFEARRAY", value.VT)
	}
	array := value.Value[0]
	if array == 0 {
		return []string{}, nil
	}
	var lower, upper int32
	if hr := hresult(call(procSafeArrayGetLBound, array, 1, uintptr(unsafe.Pointer(&lower)))); hr.failed() {
		return nil, hrError("SafeArrayGetLBound", hr)
	}
	if hr := hresult(call(procSafeArrayGetUBound, array, 1, uintptr(unsafe.Pointer(&upper)))); hr.failed() {
		return nil, hrError("SafeArrayGetUBound", hr)
	}
	result := make([]string, 0, max(int(upper-lower+1), 0))
	for index := lower; index <= upper; index++ {
		if value.VT == vtArray|vtBSTR {
			var item uintptr
			hr := hresult(call(procSafeArrayGetElement, array, uintptr(unsafe.Pointer(&index)), uintptr(unsafe.Pointer(&item))))
			if hr.failed() {
				return nil, hrError("SafeArrayGetElement", hr)
			}
			if item != 0 {
				itemPointer := *(*unsafe.Pointer)(unsafe.Pointer(&item))
				result = append(result, windows.UTF16PtrToString((*uint16)(itemPointer)))
				freeBSTR(item)
			} else {
				result = append(result, "")
			}
			continue
		}
		var item variant
		hr := hresult(call(procSafeArrayGetElement, array, uintptr(unsafe.Pointer(&index)), uintptr(unsafe.Pointer(&item))))
		if hr.failed() {
			return nil, hrError("SafeArrayGetElement", hr)
		}
		text, err := item.asString()
		item.clear()
		if err != nil {
			return nil, err
		}
		result = append(result, text)
	}
	return result, nil
}

func (value *variant) clear() {
	if value != nil && value.VT != vtEmpty {
		procVariantClear.Call(uintptr(unsafe.Pointer(value)))
		*value = variant{}
	}
}

func allocBSTR(value string) (uintptr, error) {
	pointer, err := windows.UTF16PtrFromString(value)
	if err != nil {
		return 0, err
	}
	result, _, _ := procSysAllocString.Call(uintptr(unsafe.Pointer(pointer)))
	if result == 0 {
		return 0, fmt.Errorf("SysAllocString returned nil")
	}
	return result, nil
}

func freeBSTR(value uintptr) {
	if value != 0 {
		procSysFreeString.Call(value)
	}
}

func (info exceptionInfo) text() string {
	parts := make([]string, 0, 2)
	if info.Source != nil {
		parts = append(parts, "source="+windows.UTF16PtrToString(info.Source))
	}
	if info.Description != nil {
		parts = append(parts, "description="+windows.UTF16PtrToString(info.Description))
	}
	if len(parts) == 0 {
		return ""
	}
	return "; EXCEPINFO " + strings.Join(parts, ", ")
}

func (info *exceptionInfo) clear() {
	if info.Source != nil {
		procSysFreeString.Call(uintptr(unsafe.Pointer(info.Source)))
	}
	if info.Description != nil {
		procSysFreeString.Call(uintptr(unsafe.Pointer(info.Description)))
	}
	if info.HelpFile != nil {
		procSysFreeString.Call(uintptr(unsafe.Pointer(info.HelpFile)))
	}
	*info = exceptionInfo{}
}

func release(object unsafe.Pointer) {
	if object == nil {
		return
	}
	vtable := *(*unsafe.Pointer)(object)
	method := (*[3]uintptr)(vtable)[2]
	syscall.SyscallN(method, uintptr(object))
}

func (object *iDispatch) release()            { release(unsafe.Pointer(object)) }
func (object *iWbemLocator) release()         { release(unsafe.Pointer(object)) }
func (object *iWbemServices) release()        { release(unsafe.Pointer(object)) }
func (object *iEnumWbemClassObject) release() { release(unsafe.Pointer(object)) }
func (object *iWbemClassObject) release()     { release(unsafe.Pointer(object)) }

//go:uintptrescapes
func call(proc *windows.LazyProc, arguments ...uintptr) uintptr {
	result, _, _ := proc.Call(arguments...)
	return result
}

//go:uintptrescapes
func vtableCall(method uintptr, arguments ...uintptr) uintptr {
	result, _, _ := syscall.SyscallN(method, arguments...)
	return result
}
