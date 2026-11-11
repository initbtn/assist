# [Node/TypeScript 패턴]: Zod 기반 런타임 DTO 스키마 검증 및 계층 분리

- **분류**: `backend_architecture`
- **도메인**: `fullstack_web`
- **주제**: `Node/TypeScript`
- **제목**: `Zod 스키마 기반 입력 유효성 검증 및 Fat Controller 분리`
- **우선순위**: `high`

## 규칙 개요
1. **런타임 타입 경계 방어**: TypeScript의 정적 타입은 런타임에 소거되므로, 외부 입력(HTTP Request Body, Query)은 반드시 Zod 등의 스키마 검증 라이브러리를 통해 파싱 및 검증(Fail-Fast)해야 합니다.
2. **Thin Controller & Service 분리 (SoC)**: 라우트 핸들러(Controller)는 요청 검증과 HTTP 응답 매핑만 담당하고, 비즈니스 로직 및 DB 처리는 Service 함수로 위임해야 합니다.

---

### ❌ Anti-Pattern (Bad)

```typescript
// routes/users.ts
// [결함]: 타입 단언(any/as) 사용, 런타임 검증 부재, 라우트 핸들러에 DB 쿼리 및 해싱 로직 직접 혼재.
import express, { Request, Response } from 'express';
import bcrypt from 'bcrypt';
import { db } from '../db';

const router = express.Router();

router.post('/users', async (req: Request, res: Response) => {
  const { email, password, role } = req.body as any; // 런타임 타입 위험

  if (!email || !password) {
    return res.status(400).json({ error: 'Missing fields' });
  }

  // Controller 내부에 비즈니스/암호화/DB 로직 직접 수행 (Fat Controller)
  const hashedPassword = await bcrypt.hash(password, 10);
  const user = await db.query(
    'INSERT INTO users (email, password, role) VALUES ($1, $2, $3) RETURNING id, email',
    [email, hashedPassword, role || 'USER']
  );

  return res.status(201).json(user.rows[0]);
});
```

---

### ✅ Best Practice (Good)

```typescript
// schemas/user.schema.ts
// [모범]: 명확한 런타임 검증 스키마 및 정적 타입 유도
import { z } from 'zod';

export const CreateUserSchema = z.object({
  email: z.string().email(),
  password: z.string().min(8).max(64),
  role: z.enum(['USER', 'ADMIN']).default('USER'),
});

export type CreateUserInput = z.infer<typeof CreateUserSchema>;

// services/user.service.ts
// [모범]: 비즈니스 로직과 DB 처리의 캡슐화
export class UserService {
  static async createUser(input: CreateUserInput) {
    const hashedPassword = await bcrypt.hash(input.password, 10);
    return await userRepository.create({
      email: input.email,
      password: hashedPassword,
      role: input.role,
    });
  }
}

// routes/users.ts
// [모범]: Thin Controller - 검증 통과 후 서비스 위임만 수행
router.post('/users', async (req: Request, res: Response) => {
  const result = CreateUserSchema.safeParse(req.body);
  if (!result.success) {
    return res.status(400).json({ errors: result.error.flatten() });
  }

  const user = await UserService.createUser(result.data);
  return res.status(201).json(user);
});
```
