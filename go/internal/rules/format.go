package rules

import "encoding/binary"

const (
	Magic      = "UNSAFRUL"
	Version    = 1
	HeaderSize = 128

	IPv4RecordSize = 8
	IPv6RecordSize = 32
)

const (
	offMagic      = 0
	offVersion    = 8
	offGenerated  = 12
	offHash       = 20
	offIPv4Off    = 52
	offIPv4Count  = 56
	offIPv6Off    = 60
	offIPv6Count  = 64
	offSufTable   = 68
	offSufCount   = 72
	offSufBlob    = 76
	offSufBlobLen = 80
	offExcTable   = 84
	offExcCount   = 88
	offExcBlob    = 92
	offExcBlobLen = 96
	offKwTable    = 100
	offKwCount    = 104
	offKwBlob     = 108
	offKwBlobLen  = 112
)

var order = binary.LittleEndian
