; 32-bit x86, Keystone Intel syntax. EBX -> NUL-terminated UTF-8.
; Returns EAX=Unicode scalar, EBX=next byte. NUL does not advance.
; Malformed sequence returns U+FFFD and advances one byte.
; Preserves all other general registers. Flags are clobbered.
push ecx
push edx
push esi
mov esi, ebx
movzx eax, byte ptr [esi]
test eax, eax
jz done
cmp eax, 0x80
jb ascii
cmp eax, 0xc2
jb invalid
cmp eax, 0xe0
jb two
cmp eax, 0xf0
jb three
cmp eax, 0xf5
jb four
jmp invalid
two:
mov ecx, 2
and eax, 0x1f
jmp continuation
three:
mov ecx, 3
and eax, 0x0f
jmp continuation
four:
mov ecx, 4
and eax, 7
continuation:
mov edx, ecx
dec edx
next_byte:
inc esi
movzx ecx, byte ptr [esi]
cmp ecx, 0x80
jb invalid
cmp ecx, 0xbf
ja invalid
shl eax, 6
and ecx, 0x3f
or eax, ecx
dec edx
jnz next_byte
mov edx, esi
sub edx, ebx
cmp edx, 1
je check_two
cmp edx, 2
je check_three
cmp eax, 0x10000
jb invalid
cmp eax, 0x10ffff
ja invalid
jmp valid
check_two:
cmp eax, 0x80
jb invalid
jmp valid
check_three:
cmp eax, 0x800
jb invalid
cmp eax, 0xd800
jb valid
cmp eax, 0xdfff
jbe invalid
valid:
lea ebx, [esi+1]
jmp done
ascii:
inc ebx
jmp done
invalid:
mov eax, 0xfffd
inc ebx
done:
pop esi
pop edx
pop ecx
ret
